# Kabutopz Voice Protocol

Kabutopz Voice Protocol is a Windows voice-command app for *Star Citizen*. It lets you run game actions with spoken phrases, edit keybinds, create custom commands, look up mining sites, and find current ship purchase and rental data.

The app uses Windows `SendInput` to send set keybinds. It does not use the third-party `keyboard` or `mouse` hook packages.

This is an accessibility tool.

## Features

- Voice commands for common *Star Citizen* actions
- Faster voice-activity capture that submits a command shortly after you stop speaking
- Optional global keybind to toggle listening on and off
- Editable phrases and keybinds with Ctrl, Alt, Shift, Left, and Right modifiers
- Custom commands with one or more trigger phrases
- Repeating commands with a spoken stop phrase and reply
- Wake word mode — keep listening, obey only the wake phrase
- Star map voice navigation: plot and verify a course by voice
- Voice cloning — give the ship computer your own voice
- UEX commodity price and buy/sell-location lookup
- Tap and Hold input modes
- Ship purchase and rental lookups
- Mining location questions with spoken answers
- Reverse mining-signature lookup
- Links to *Star Citizen* guides and announcements
- Saved settings and custom commands between launches

## Pages

The PAGE menu includes:

- **VOICE PROTOCOL** — Start and manage voice control.
- **HOW TO** — Learn the command, resource, and custom-phrase workflow.
- **COMMODITIES** — Search UEX commodity prices and buy/sell locations.
- **CUSTOMIZE** — Change app settings.
- **PHRASES** — Edit phrases and keybinds by group.
- **CUSTOM WORDS** — Create and manage custom voice commands.
- **KEYBINDS** — Search actions and change their keys.
- **STAR MAP** — Calibrate and test voice course plotting.
- **VOICE CLONES** — Record, render and switch cloned voices.
- **MINING MODE** — Use mining tools and signature lookup.
- **SHIP FINDER** — Find ship purchase and rental details.
- **GUIDES** — Open the Kabutopz *Star Citizen* guides playlist on YouTube.
- **ANNOUNCEMENTS** — Open the official Spectrum Announcements forum.

## Voice Commands

While Voice Protocol is listening, speak a saved phrase to run its linked keybind.

For example:

```text
turn off star citizen
```

This command sends `Alt+F4`.

### Faster recognition

The microphone now waits for speech and submits the audio about 0.45 seconds
after you stop talking, instead of holding every command for a fixed four
seconds. Short commands should feel substantially faster. Internet speed and
Google's speech-recognition response time can still add a small delay.

Saying `computer turn off` confirms the command and adds, “Thank you for
flying with me.” Saying `thank you computer` (or `thanks computer`) receives a
random friendly reply.

### Listening toggle keybind

Under **VOICE PROTOCOL**, set an optional keybind under **VOICE ACTIVATION
TOGGLE KEYBIND**. It works globally, so it can turn listening on or off while
*Star Citizen* has focus.

Examples: `F8`, `Ctrl+Shift+V`, or `Alt+F10`.

It is blank by default. Leave it blank or use **CLEAR** to disable the toggle.
If Windows reports that a chosen key is already in use, choose another one.

## Custom Words

The **CUSTOM WORDS** page lets you:

- Name a new action.
- Pick an existing subcategory or enter a new one.
- Set a keybind, including Ctrl, Alt, Shift, and Left/Right modifier variants.
- Choose Tap or Hold.
- Add more than one trigger phrase.
- Turn each phrase on or off.
- Save the command for later use.

Saved custom commands join the normal voice matching list. They also appear in the **CUSTOM PHRASES** group on the **PHRASES** page.

To remove saved items, select a command under **EXISTING CUSTOM COMMANDS**, then use:

- **DELETE SELECTED PHRASE** to remove one phrase.
- **DELETE CUSTOM COMMAND** to remove the full command.

Each custom command must keep at least one phrase.

## Keybind Search

The **KEYBINDS** page can search by key, action, phrase, or category.

Use **FILTER BY KEYBIND** for an exact key match. For example, entering `K`, `I`, `F12`, or `alt+f4` shows only actions set to that keybind. This mode does not match action names or phrase text.

Use **SEARCH ALL** for a broad search, or **CLEAR** to reset the results.

## Ship Finder

Search for a ship by name, such as:

```text
Cutlass Black
```

The app checks the public Star Citizen Wiki community API and tries to show:

- Purchase locations
- Purchase prices
- Rental locations
- Rental prices

The app includes a Cutlass Black backup snapshot in case the live price format changes or the service cannot return data. Community data may change with each game patch.

## Mining Questions

While Voice Protocol is listening, ask a question such as:

```text
where can I mine iron
```

The app checks current Star Citizen Wiki commodity data and speaks the answer. If the live lookup fails, it uses a saved Iron hotspot list.

The existing reverse signature lookup remains on the **MINING MODE** page.

## Star Map Navigation

Say **"open star map"** to press F2, wait for the mobiGlas, click into the
search bar, and reply *"Ready to plot course."* Then:

```text
plot a course to Grim Hex
take me to Lorville
route to CRU-L5
```

The app types the destination, picks the right row from the results, and
presses R to route — then checks that a course was actually plotted before
saying so.

Two things make this reliable rather than lucky:

**Nothing is timed; everything is checked.** The bottom-right keybind list is
a state machine the app can read — `LOCAL MAP` means the map is open,
`SET ROUTE` means a target is selected, `CANCEL ROUTE` means a course is
plotted. Each step waits for the game to say it is ready instead of guessing
at a delay.

**Results are grouped by star system, and the app reads the headers.** Both
Stanton and Pyro have a NYX GATEWAY; the header above the row is the only
thing that tells them apart. If a destination is in another system you get the
useful answer — *"Grim Hex is in the Stanton system. Travel to the Stanton
Gateway first."* — rather than a silent failure.

### Names the recogniser gets wrong

Spoken destinations rarely arrive spelled the way the game writes them, so:

| You say | It types |
|---|---|
| "grim hicks" | Grim Hex |
| "CRU L5" | cru-l5 |
| "H U R L 3" (spelled out) | hur-l3 |
| "lorville" heard as "lorevile" | falls back to `lor` |

Destinations are typed in lower case on purpose. Capitals need Shift, the game
samples modifier state per frame, and `HUR-L5` used to arrive as `HUR_L%`.
Lower case needs no Shift at all.

If the full name finds nothing, the app retries with progressively shorter
prefixes down to three letters — the game filters as you type, so a mis-heard
ending is fatal but a mis-heard start is rare.

## Repeating Commands

Any command can repeat on an interval, with its own stop phrase and reply.
Set it up under **CUSTOM WORDS**:

- Trigger: `away from keyboard` → presses F1 every 60 seconds
- Stop phrase: `I'm back` → stops it and replies *"Welcome back."*

Running repeats appear in **ACTIVE REPEATS** on the VOICE PROTOCOL page and
can be stopped there, by their own stop phrase, or by saying `stop repeating`.
They all stop when voice control stops. Self-destruct, goon mode and quitting
the game refuse to repeat at all.

## Wake Word Mode

Say **"voice off"** and the microphone stays open but stops obeying — only the
wake phrase gets through. For talking to people without your ship reacting to
the conversation.

- Sleep: `voice off`, `computer voice off`, `go to sleep`
- Wake: `computer turn voice on`, `computer start listening`

All four phrases and both replies are editable on the **CUSTOMIZE** page. The
status word changes to `WAKE WORD MODE`, so the app never claims to be
listening while it is deliberately ignoring you.

While asleep, *nothing else* is acted on — including a running repeat's stop
phrase. Wake it first, then say your stop phrase.

This is different from `computer turn off`, which ends listening entirely.

## Voice Clones

Give the ship computer a voice of your own. Record about ten seconds, and
every line it can say is rendered once — after that, speaking is just playing
a file.

**Nothing runs while you fly.** No model is loaded, no VRAM is taken from the
game, and there is no delay before a reply. That is the whole design.

### Installing Voice Forge (one time)

Voice cloning needs PyTorch — around 2 GB — so it lives in its own optional
folder rather than inside the app. The app works with the Windows voice
whether or not you install it.

1. Open `voice_forge\` beside `KabutopzVoiceProtocol.exe`
2. Run **`setup_voice_forge.bat`**

It detects an NVIDIA GPU and installs the matching build. To choose yourself:

```text
setup_voice_forge.bat cuda     NVIDIA - about 3.5 GB, seconds per line
setup_voice_forge.bat cpu      no GPU needed - about 1 GB, ~20 seconds per line
```

**CPU is a real choice, not a booby prize.** On a machine with unified memory —
a GMK EVO-X2 or similar mini-PC — there is no separate VRAM to win by moving
the model onto the GPU, and the CUDA wheels are 2.5 GB you would never use.

The model weights (about 1 GB) download the first time you render, not during
setup.

### Making a voice

On the **VOICES** page:

1. Type a **name** — say it the way you will speak it, since you will be
   saying "switch to *name* voice"
2. **RECORD 12 SECONDS** using your configured microphone, or **IMPORT A WAV
   FILE**
3. Read the script shown on the page. Somewhere quiet
4. Say yes when it offers to render

A raw take is trimmed automatically: the app measures loudness across the
recording, finds where the speech is against the recording's own noise floor,
and keeps the densest ten seconds — starting on a word rather than
mid-syllable. You do not need an audio editor.

**Record somewhere quiet.** Room echo, background music and a second voice all
get encoded into the clone alongside you. A clean ten seconds beats a noisy
thirty.

A full render is about 155 lines: roughly **7 minutes on an RTX 3060**, or
about an hour on CPU.

> **Close Star Citizen before rendering.** Measured on an RTX 3060: five lines
> took 12.9s on a free card, 102s on CPU, and **255s on the GPU while Star
> Citizen was running**. A contended graphics card is worse than no graphics
> card. The renderer warns you if VRAM is short.

### Using a voice

Select it and press **USE THIS VOICE**, or say:

```text
switch to ship computer voice
computer athena voice
use the windows voice
```

It confirms with *"Voice calibrated."* — spoken in the voice you just chose,
which is how you know the switch landed.

Names are matched loosely, because a name is not a dictionary word: "Captain
FasciN8" comes back from the recogniser as "captain fascinate" and still
resolves.

### Variable text falls back automatically

"Course set to Grim Hex. 1 minute, 23 seconds." is two different things: a
sentence worth cloning, and a travel time that is different every flight.

Speech is split into sentences and each is spoken by whichever voice has it —
the cloned voice for the part that repeats, the Windows voice for the part
that never does. Travel times and distances are never rendered and never
queued, because a clip used once is a clip wasted.

### Fixing a bad line

Chatterbox occasionally produces a garbled take. Select the voice, press
**REVIEW LINES**, double-click any line to hear it, and **RE-RENDER THIS
LINE** on one that came out wrong. It goes back on the pending list; RENDER
MISSING LINES redoes just that one.

You never have to re-render a whole voice to fix a single line.

### Keeping a voice current

Any reply you type — a custom command's start or stop reply, either wake-word
response — is added to the render list automatically. Press **RENDER MISSING
LINES** to catch up.

The app also writes down any line it needed and did not have, so the list
offers exactly what actually came up in your flying rather than asking you to
guess. When you close the app with a cloned voice active and lines
outstanding, it offers to render them — which is the right moment, because
that is when the graphics card is free.

### Where voices live

```text
%USERPROFILE%\.star_citizen_voice_keybinds\voices\
    ship-computer\
        voice.json        name, engine, settings
        reference.wav     the audio it was cloned from
        missing.json      lines needed but not yet rendered
        clips\            one WAV per rendered line
```

Plain folders and plain JSON. Back a voice up, copy it to another machine, or
delete it in Explorer — the app will keep up. A full voice is about 21 MB.

### Whose voice

Clone your own voice, or one whose owner has agreed. A voice clone can say
*anything* in that voice, which is why this matters more than it might seem.
Cloning a public figure, an actor, or a character performance from show audio
is someone else's voice and someone else's living.

## Support

The header includes a Buy Me a Coffee link. Click the support text, button image, or box to open:

[buymeacoffee.com/kabutopz](https://buymeacoffee.com/kabutopz)

## Build

### Requirements

- Windows 10 or Windows 11
- Python 3 with `pip`
- The packages listed in `requirements.txt`
- An internet link for live ship and mining data

The app does not need the third-party `keyboard` or `mouse` hook packages. It sends game input through Windows `SendInput`.

The project uses these Python packages:

```text
SpeechRecognition>=3.10.4
sounddevice>=0.5.0
pyinstaller>=6.10
Pillow>=10.0
```

Save this list as `requirements.txt` in the project folder if that file is not already present.

### Install Dependencies

Open Command Prompt or PowerShell in the project folder. Create a virtual environment so the app's packages stay apart from your main Python setup:

```bat
py -m venv .venv
```

Start the virtual environment:

```bat
.venv\Scripts\activate
```

Update `pip`, then install the project packages:

```bat
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

This installs SpeechRecognition, sounddevice, Pillow, and PyInstaller. The build script uses PyInstaller to make the Windows app.

When you finish, you can leave the virtual environment with:

```bat
deactivate
```

### Create the App

Run this file from the project folder:

```bat
build_exe.bat
```

Run the build while the virtual environment is active so PyInstaller can include the right packages.

The build creates:

```text
dist\KabutopzVoiceProtocol\KabutopzVoiceProtocol.exe
```

Keep the full `KabutopzVoiceProtocol` folder together when you run or share the app. The build uses PyInstaller's one-folder mode, so the executable needs the other files in that folder.

The build also creates:

```text
dist\KabutopzVoiceProtocol\SHA256.txt
```

Use this file to check that the release files have not changed.

## Release Notes

The Windows build:

- Uses one-folder mode instead of a self-unpacking one-file build.
- Turns off UPX packing.
- Includes company, product, file, and version details.
- Bundles the app icons, logo art, and Buy Me a Coffee image.
- Creates a SHA-256 hash after each successful build.
- Requests administrator permission at launch so configured keys can be sent to the game reliably.

These steps can help cut false antivirus alerts, but no clean build can promise zero alerts from every antivirus tool. For public releases, sign each build with the same trusted code-signing certificate.

## Data Notice

Ship and commodity results come from the community-run Star Citizen Wiki API. The data may lag behind game updates, and fields may change without notice.

## Version

Kabutopz Voice Protocol v1.2
Powered by the Community <3

Future releases increment by 0.1: 1.0, 1.1, through 1.9, then 2.0.
