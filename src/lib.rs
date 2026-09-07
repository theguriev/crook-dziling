//! dziling: a Crook plugin that rings when a command finishes.
//!
//! It does one thing. When the shell says a command ended — OSC 133 `D`, which
//! is the same mark Crook's own blocks are cut by — this asks the host to play
//! a short sound. That is the whole plugin.
//!
//! # Why it asks rather than plays
//!
//! A sandboxed plugin reaches nothing. It has six imports and none of them is
//! a device: to make a sound it encodes a [`Request::PlaySound`] carrying the
//! audio and hands it to `crook.request`, and the host — which checked the
//! grant first — spawns a player off the frame thread. So the worst this
//! module can do to a window is spend its own fuel.
//!
//! # Why the sounds are inside the module
//!
//! Six wavs, embedded with `include_bytes!`. They could have been files beside
//! the module, but reading them would cost [`Capability::ReadFiles`] over the
//! plugin's own directory — a capability a person would have to grant and
//! could not picture the consequences of — to read files that were installed
//! at the same moment as the module itself. Bytes in the module need no
//! permission at all, and what they are is fixed at build time where anybody
//! can see it.
//!
//! Every one of them is synthesised, not sampled: `tools/voices/*.py` builds
//! each from oscillators and filters, and CI fails if the committed wavs are
//! not what that source produces. Nothing here is anybody else's audio.

use std::alloc::{Layout, alloc, dealloc};
use std::cell::RefCell;

use crook_plugin_api::{
    ABI_VERSION, Capability, Event, Gap, Manifest, Node, Request, Size, Tone, from_bytes,
    to_bytes,
};

/// What the host is told this plugin is.
const ID: &str = "theguriev/dziling";

/// How loud, out of 100.
///
/// Not configurable yet, and honestly rather than quietly: the ABI has a
/// `Storage` capability but no request that reaches it, so anything a person
/// changed would last until they closed the window. A default that is a little
/// too quiet is a better place to stand than a setting that forgets.
const VOLUME: u8 = 70;

/// How long a command has to run before finishing it is worth a sound.
///
/// Two seconds. Below it are the commands nobody is waiting on — `cd`, `ls`,
/// a `git status` — and a terminal that dinged at those would be unusable
/// within a minute. Above it is the case this plugin exists for: something
/// took long enough that a person looked away.
const MIN_MILLIS: u64 = 2_000;

/// The sounds, in the order the list on the card offers them.
///
/// `dzin` first because it is the default: a small bell is the one of these
/// that survives being heard forty times a day.
const SOUNDS: &[Sound] = &[
    Sound {
        name: "dzin",
        label: "Dzin",
        wav: include_bytes!("../sounds/dzin.wav"),
    },
    Sound {
        name: "microwave",
        label: "Microwave",
        wav: include_bytes!("../sounds/microwave.wav"),
    },
    Sound {
        name: "engine",
        label: "Engine",
        wav: include_bytes!("../sounds/engine.wav"),
    },
    Sound {
        name: "coin",
        label: "Coin",
        wav: include_bytes!("../sounds/coin.wav"),
    },
    Sound {
        name: "sonar",
        label: "Sonar",
        wav: include_bytes!("../sounds/sonar.wav"),
    },
    Sound {
        name: "typewriter",
        label: "Typewriter",
        wav: include_bytes!("../sounds/typewriter.wav"),
    },
];

/// One sound this plugin can ring.
struct Sound {
    /// What the action after `dziling/` is called, and what a chord binds.
    name: &'static str,
    /// The one word the list and the badge carry.
    label: &'static str,
    /// The audio itself.
    wav: &'static [u8],
}

/// What the plugin remembers between calls.
///
/// A `thread_local` because wasm is single-threaded and this is the whole of
/// the state: which sound is on, and whether it rings at all.
struct State {
    /// Index into [`SOUNDS`].
    chosen: usize,
    /// Whether a finished command rings.
    ringing: bool,
    /// Whether the sound list is hanging open under the control.
    ///
    /// The plugin's, not the host's: `Node::Anchored` draws a panel on every
    /// frame this is true and none where it is not, and the host tells the
    /// plugin when a click outside shut it.
    open: bool,
}

thread_local! {
    static STATE: RefCell<State> = const {
        RefCell::new(State { chosen: 0, ringing: true, open: false })
    };
    /// Where a value the host is about to read is kept alive.
    ///
    /// One buffer, overwritten per call. The host reads what a call returned
    /// before it calls anything else, so the only lifetime this has to survive
    /// is the return itself.
    static OUTBOX: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
}

// The imports the host installs. See `crook_wasm`'s `imports` module.
#[link(wasm_import_module = "crook")]
unsafe extern "C" {
    #[link_name = "contribute"]
    safe fn host_contribute(
        slot: *const u8,
        slot_len: i32,
        entry: *const u8,
        entry_len: i32,
        order: i32,
    );
    #[link_name = "register_action"]
    safe fn host_register_action(name: *const u8, name_len: i32, title: *const u8, title_len: i32);
    #[link_name = "request"]
    safe fn host_request(pointer: *const u8, length: i32) -> i32;
    #[link_name = "log"]
    safe fn host_log(level: i32, text: *const u8, length: i32);
}

/// Says something in Crook's log, at info.
fn log(text: &str) {
    host_log(3, text.as_ptr(), text.len() as i32);
}

/// The slot a plugin may say what it is doing on, drawn on its own card.
const CARD_SLOT: &str = "plugins.card.status";

/// Puts this plugin's one entry on a slot.
fn contribute(slot: &str, entry: &str, order: i32) {
    host_contribute(
        slot.as_ptr(),
        slot.len() as i32,
        entry.as_ptr(),
        entry.len() as i32,
        order,
    );
}

/// Registers one action under this plugin's own name.
fn register(name: &str, title: &str) {
    host_register_action(
        name.as_ptr(),
        name.len() as i32,
        title.as_ptr(),
        title.len() as i32,
    );
}

/// Registers an action that is reachable but not offered anywhere.
fn register_quietly(name: &str) {
    host_register_action(name.as_ptr(), name.len() as i32, core::ptr::null(), 0);
}

/// Hands the host something to do, and says whether it took it.
fn ask(request: &Request) -> bool {
    let Ok(bytes) = to_bytes(request) else {
        return false;
    };
    host_request(bytes.as_ptr(), bytes.len() as i32) != 0
}

/// Packs a pointer and a length the way every returning export does.
fn packed(bytes: Vec<u8>) -> i64 {
    OUTBOX.with(|outbox| {
        let mut outbox = outbox.borrow_mut();
        *outbox = bytes;
        (i64::from(outbox.as_ptr() as u32) << 32) | i64::from(outbox.len() as u32)
    })
}

/// Reads what the host wrote into memory it asked this module for, and gives
/// that memory back.
///
/// # Safety
///
/// Only ever called on a pointer and length the host got from
/// [`crook_alloc`], which is the only way it has to put bytes here.
unsafe fn taken(pointer: *mut u8, length: i32) -> Vec<u8> {
    if pointer.is_null() || length <= 0 {
        return Vec::new();
    }
    let length = length as usize;
    let bytes = unsafe { std::slice::from_raw_parts(pointer, length) }.to_vec();
    // Freed with exactly the layout `crook_alloc` used; anything else is
    // undefined behaviour rather than a leak.
    if let Ok(layout) = Layout::from_size_align(length, 1) {
        unsafe { dealloc(pointer, layout) };
    }
    bytes
}

/// The version of the vocabulary this was built against.
#[unsafe(no_mangle)]
pub extern "C" fn crook_abi_version() -> i32 {
    ABI_VERSION as i32
}

/// Memory for the host to put something in.
#[unsafe(no_mangle)]
pub extern "C" fn crook_alloc(length: i32) -> i32 {
    if length <= 0 {
        return 0;
    }
    let Ok(layout) = Layout::from_size_align(length as usize, 1) else {
        return 0;
    };
    // Null on failure rather than a panic: the host reads a zero as "it could
    // not", and a guest that aborted here would take its own plugin down over
    // an allocation it could have declined.
    unsafe { alloc(layout) as i32 }
}

/// What this plugin says about itself, before any of it runs.
#[unsafe(no_mangle)]
pub extern "C" fn crook_manifest() -> i64 {
    let manifest = Manifest {
        abi: ABI_VERSION,
        id: ID.into(),
        name: "dziling".into(),
        description: "Rings a short sound when a command finishes.".into(),
        version: env!("CARGO_PKG_VERSION").into(),
        // Exactly two, and both are things a person can picture: it hears that
        // commands ended, and it makes a noise. It asks for no network, no
        // files, no clipboard and nothing about the tabs.
        capabilities: vec![Capability::WatchCommands, Capability::PlaySound],
    };
    match to_bytes(&manifest) {
        Ok(bytes) => packed(bytes),
        Err(_) => 0,
    }
}

/// Registers what this plugin offers.
///
/// One line on its own card, and one action per choice. Nothing in the header:
/// a badge up there saying "a sound will play" would be worse than the sound.
///
/// # Why only one of them is offered
///
/// A command is an action a person should be able to *find*; the card lists
/// every one of them under the contribution, as a row with a Run button. So a
/// plugin that draws a select and a play mark and also offers eight commands
/// gets the same eight things twice on the same card — once in the shape it
/// chose and once in the shape the card invented, the second one three times
/// longer than the first. Picking a sound and hearing it are what the control
/// is *for*, so they are registered quietly and the list collapses to the one
/// thing the control does not do.
///
/// What that costs is real and is paid for in [`sheet`]: the six names leave
/// the palette and the Keyboard Shortcuts page with their titles, so the note
/// under the control writes them out. A name nobody can read is a chord nobody
/// can bind.
#[unsafe(no_mangle)]
pub extern "C" fn crook_build() -> i32 {
    contribute(CARD_SLOT, "status", 0);
    // Reachable and not offered, the way a palette registers its own arrow
    // keys: the list on the card is where a sound is picked, and opening that
    // list is what the control does rather than something anybody should find
    // in a palette and wonder about.
    for sound in SOUNDS {
        register_quietly(sound.name);
    }
    register_quietly("test");
    register_quietly("open");
    register_quietly("close");
    // The one thing the control does not do, and the one worth a palette
    // entry: muting is set once and then left, which is what a palette is for
    // and what a control somebody has to open a settings page to reach is not.
    register("toggle", "dziling: mute or unmute");
    0
}

/// Everything the card's list used to say, hung off the control that says
/// which sound is chosen.
///
/// It is here because it is about *this* control, and a note about a control
/// belongs on it: the card's version was eight action names in a column under
/// a select that already reached seven of them. It costs the wire its bytes on
/// every frame rather than only on the frames a pointer is over the chip —
/// which is the trade [`Node::Explained`] is, and the alternative was a call
/// into this module every time a mouse crossed it.
///
/// It writes the six action names out because nothing else does any more.
/// [`crook_build`] registers them quietly, so they are gone from the palette
/// and from the Keyboard Shortcuts page; they are still bindable, and this is
/// where somebody finds out what to bind.
fn sheet(state: &State) -> Node {
    Node::Column(vec![
        // What the row's badge says, said again with the word the badge cannot
        // carry: a muted-toned pill and an accented one are one glance apart,
        // and this is the surface with room to say which is which.
        Node::Row(vec![
            Node::Text {
                text: SOUNDS[state.chosen].label.into(),
                size: Size::Body,
                tone: Tone::Primary,
            },
            Node::Fill,
            Node::Badge {
                text: if state.ringing { "ringing" } else { "muted" }.into(),
                tone: if state.ringing {
                    Tone::Accent
                } else {
                    Tone::Muted
                },
            },
        ]),
        Node::Note {
            text: "Rings when a command that ran for two seconds or more finishes.".into(),
            tone: Tone::Muted,
        },
        Node::Rule,
        Node::Note {
            text: "Six sounds. Click to choose one \u{2014} picking it plays it, so the \
                   choice is made by ear."
                .into(),
            tone: Tone::Muted,
        },
        Node::Note {
            text: "Bind one to a chord by name: theguriev/dziling/dzin, and microwave, \
                   engine, coin, sonar, typewriter."
                .into(),
            tone: Tone::Muted,
        },
        Node::Note {
            text: "The triangle plays whichever is chosen, muted or not.".into(),
            tone: Tone::Muted,
        },
        Node::Note {
            text: "\u{201c}dziling: mute or unmute\u{201d}, in the palette, stops the ring \
                   without switching the plugin off."
                .into(),
            tone: Tone::Muted,
        },
    ])
}

/// A select saying which sound is chosen, and a mark that plays it.
///
/// A select rather than a list of nine identical rows, which is what this was
/// and what made three different buttons look like one that sometimes works.
/// Every piece of it is in the vocabulary already: `Anchored` hangs the list
/// under the control the host places and sizes, `Explained` hangs [`sheet`]
/// over it while the pointer is on it, and `Pressable` makes each row of the
/// list run the action that picks that sound.
///
/// The play mark is a `Pressable` and not a `Button` for the reason it stopped
/// looking like a player: a `Button` is drawn the way the card's own Run
/// buttons are drawn, so the one control this plugin exists for was a grey box
/// reading "Play" stacked above eight grey boxes reading "Run". A triangle and
/// a word, on a ground that appears when it is reached for, is a thing that
/// plays something.
#[unsafe(no_mangle)]
pub extern "C" fn crook_render(request: *mut u8, length: i32) -> i64 {
    // Freed rather than read: what this draws is the same on every slot it is
    // contributed to, and bytes the host allocated through `crook_alloc` and
    // nobody gave back are a leak once a frame.
    let _ = unsafe { taken(request, length) };

    let node = STATE.with(|state| {
        let state = state.borrow();
        let sound = &SOUNDS[state.chosen];

        // The list, drawn only while it is open. `None` is a shut panel, and
        // the host takes it away itself when a click lands outside.
        let panel = state.open.then(|| {
            Box::new(Node::Column(
                SOUNDS
                    .iter()
                    .enumerate()
                    .map(|(index, option)| Node::Pressable {
                        content: Box::new(Node::Row(vec![
                            // The chosen one is accented rather than ticked:
                            // there is no tick in the vocabulary, and a tone
                            // is what the host resolves against the theme.
                            Node::Text {
                                text: option.label.into(),
                                size: Size::Body,
                                tone: if index == state.chosen {
                                    Tone::Accent
                                } else {
                                    Tone::Primary
                                },
                            },
                        ])),
                        action: option.name.into(),
                    })
                    .collect(),
            ))
        });

        let select = Node::Anchored {
            content: Box::new(Node::Pressable {
                content: Box::new(Node::Row(vec![
                    Node::Badge {
                        text: sound.label.into(),
                        tone: if state.ringing {
                            Tone::Accent
                        } else {
                            Tone::Muted
                        },
                    },
                    Node::Gap(Gap::Small),
                    Node::Icon {
                        name: "chevron-down".into(),
                        tone: Tone::Muted,
                    },
                ])),
                action: "open".into(),
            }),
            panel,
            dismiss: "close".into(),
        };

        Node::Row(vec![
            Node::Text {
                text: "Rings".into(),
                size: Size::Small,
                tone: Tone::Muted,
            },
            Node::Gap(Gap::Small),
            // Explained only while the list is shut. The panel is drawn by
            // this same subtree, so a pointer down in the list still counts as
            // a pointer on the chip — and the note would come up beside the
            // list it is a note about, over the sounds somebody is reading.
            if state.open {
                select
            } else {
                Node::Explained {
                    content: Box::new(select),
                    explanation: Box::new(sheet(&state)),
                }
            },
            Node::Gap(Gap::Medium),
            Node::Pressable {
                content: Box::new(Node::Row(vec![
                    Node::Icon {
                        name: "play".into(),
                        tone: Tone::Accent,
                    },
                    Node::Gap(Gap::Small),
                    Node::Text {
                        text: "Play".into(),
                        size: Size::Small,
                        tone: Tone::Accent,
                    },
                ])),
                action: "test".into(),
            },
            // One word, only when it is off. The badge going quiet says it
            // too, but a tone is a thing you notice once you know to look; how
            // to undo it is in the note rather than here, because a row that
            // grew an instruction whenever it was muted was a row that changed
            // shape under the pointer.
            if state.ringing {
                Node::Empty
            } else {
                Node::Row(vec![
                    Node::Gap(Gap::Medium),
                    Node::Text {
                        text: "muted".into(),
                        size: Size::Small,
                        tone: Tone::Warning,
                    },
                ])
            },
        ])
    });
    match to_bytes(&node) {
        Ok(bytes) => packed(bytes),
        Err(_) => 0,
    }
}

/// Runs one of the actions above.
///
/// # Why it takes four numbers rather than two
///
/// Because that is what the host calls: `crook_run(name, name_len, argument,
/// argument_len)`. The argument is whatever the thing that was pressed had to
/// say — the key of a chosen row, the entry of a menu — and nothing this
/// plugin draws has anything to say, so it is taken and dropped. It cannot be
/// left off the signature: wasmi looks the export up *by type*, so a
/// two-parameter `crook_run` is not a `crook_run` the host can find, and every
/// action in this plugin failed at that lookup rather than inside it. Which is
/// what a select that does not open and a play mark that makes no noise both
/// were.
///
/// Both strings were written through [`crook_alloc`], so both are freed here
/// rather than leaked once per press.
#[unsafe(no_mangle)]
pub extern "C" fn crook_run(
    name: *mut u8,
    length: i32,
    argument: *mut u8,
    argument_len: i32,
) -> i32 {
    let bytes = unsafe { taken(name, length) };
    let _ = unsafe { taken(argument, argument_len) };
    let Ok(action) = std::str::from_utf8(&bytes) else {
        return 0;
    };

    match action {
        // The list is the plugin's own state; the host only draws what the
        // last frame said and tells us when a click outside shut it.
        "open" => STATE.with(|state| {
            let mut state = state.borrow_mut();
            state.open = !state.open;
        }),
        "close" => STATE.with(|state| state.borrow_mut().open = false),
        "toggle" => STATE.with(|state| {
            let mut state = state.borrow_mut();
            state.ringing = !state.ringing;
        }),
        // The one button whose whole job is to make a noise. Everything else
        // that used to make one — picking the sound already picked, switching
        // the plugin back on — no longer does, because three controls that all
        // played the current sound read as one control that sometimes works.
        "test" => preview(),
        chosen => {
            if let Some(index) = SOUNDS.iter().position(|sound| sound.name == chosen) {
                STATE.with(|state| {
                    let mut state = state.borrow_mut();
                    state.chosen = index;
                    state.open = false;
                    // Picking a sound is also asking to hear it, so a choice
                    // made while muted unmutes rather than silently doing
                    // nothing visible.
                    state.ringing = true;
                });
                ring();
            }
        }
    }
    0
}

/// Something happened.
#[unsafe(no_mangle)]
pub extern "C" fn crook_event(pointer: *mut u8, length: i32) -> i32 {
    let bytes = unsafe { taken(pointer, length) };
    let Ok(event) = from_bytes::<Event>(&bytes) else {
        // A shape this build does not know is one to ignore, not to trap on:
        // a newer host may send an event this version was written before.
        return 0;
    };

    match event {
        Event::CommandFinished { took_millis, .. } => {
            // Unknown means it was already running when Crook started
            // watching, which is exactly the long-running case this is for.
            if took_millis.unwrap_or(u64::MAX) >= MIN_MILLIS {
                ring();
            }
        }
    }
    0
}

/// Nothing is ever asked for that needs an answer, but the export exists
/// because `PlaySound` is a request and a request without somewhere to deliver
/// its answer is one the host declines to start.
#[unsafe(no_mangle)]
pub extern "C" fn crook_deliver(_ticket: i32, pointer: *mut u8, length: i32) -> i32 {
    // Freed rather than read: whether the sound played is not something this
    // plugin can do anything about, and holding on to the bytes would leak one
    // answer per chime.
    let _ = unsafe { taken(pointer, length) };
    0
}

/// Plays the chosen sound when a command finishing should be heard.
///
/// This one obeys the mute; [`preview`] does not. They were the same function
/// once, and that made the Play button silent whenever ringing was switched
/// off — a button whose whole job is to make a noise, obeying a switch about
/// something else entirely, reads as a button that does not work.
fn ring() {
    if STATE.with(|state| !state.borrow().ringing) {
        return;
    }
    preview();
}

/// Plays the chosen sound because somebody asked to hear it, mute or not.
fn preview() {
    let wav = STATE.with(|state| {
        let state = state.borrow();
        SOUNDS[state.chosen].wav
    });
    if !ask(&Request::PlaySound {
        wav: wav.to_vec(),
        volume: VOLUME,
    }) {
        // The host's queue is full, which means something is very wrong with
        // this plugin's own scheduling. One line, and no retry: a chime that
        // arrives late is worse than one that does not arrive.
        log("dziling: the host would not take the sound");
    }
}
