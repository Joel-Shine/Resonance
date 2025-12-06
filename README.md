<div align="center">

# 🎵 Resonance

**The Terminal Audio Experience.**

A premium, CLI-based music streamer built for audiophiles who live in the terminal.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![VLC](https://img.shields.io/badge/Engine-LibVLC-orange)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

**Resonance** is not just a wrapper for a media player. It acts as a digital DJ, utilizing a custom **Dual-Deck Architecture** to manage two simultaneous audio streams. This allows for seamless, broadcast-quality crossfading between tracks without the silence gaps found in standard CLI players.

## ✨ Key Features

* **🎛 Dual-Deck Audio Engine:** Two independent VLC instances manage current and next tracks, enabling true overlap crossfading for a surreal audio experience.
* **🌊 Seamless Playback:** Zero-latency transitions. The next song is pre-buffered and "warmed up" in the background before the current song ends.
* **📊 Live Visualizer:** A responsive, multi-row spectrum analyzer built entirely with ASCII/Unicode blocks.
* **⚡ Zero-Lag UI:** The audio engine runs on high-priority threads, ensuring the UI remains buttery smooth (60fps) even during network fetches.
* **🧠 Smart Caching:** Playlist searches are cached locally (`.json`). Re-playing a 100-song playlist is instant.
* **📂 Easy Import:** Import playlists via simple `.txt` files.

## 🖼️ Demo
![Demo for Resonance](https://github.com/Joel-Shine/Resonance/blob/main/demo.PNG)

## 🛠️ Installation
### !! Currently Resonance is supported only in Windows. 
Resonance relies on **VLC Media Player** for its audio decoding core.
* **Windows:** Install [VLC Media Player](https://www.videolan.org/vlc/).
* **FFmpeg:** (Optional but recommended) Install FFmpeg and add it to your PATH for better stream handling.

### 🚀 Usage
Run the player directly from your terminal:
```bash
python streamer.py
```

### Controls
| Keys     |                    Actions                      |
| -------- | ------------------------------------------------|
| s        |               search for a song                 |
| i        |     import a playlist file (playlist.txt)       |
| Enter    | Play the currently selected song (Jump to track)|
| p        |                Pause playback                   |
| r        |                Resume playback                  |
| q        |             Quit the application                |
| ↑ / ↓    |            Navigate the queue/menun             |
| ← / →    |           Seek backward/forward (5s)            |

### 📂 Playlist Format
To import a playlist, create a simple text file (e.g., vibes.txt) in the project folder with one song name per line:
```text
Starboy
Hotel California
Bohemian Rhapsody
Blinding Lights
```
Then, press <b>"i"</b> in the app and type <b>"vibes"</b>. Resonance will auto-fetch, cache, and queue these tracks.

### 🏗️ Architecture
1. Main Thread: Handles the Rich TUI rendering and User Input.
2. Queue Manager: A background daemon that constantly monitors the Next Deck. If it's empty, it fetches the next stream URL and pre-loads it.
3. Crossfade Worker: A specialized thread that wakes up 5 seconds before a song ends to perform the logarithmic volume handoff between Deck A and Deck B.
4. Silence Guard: A startup routine that suppresses VLC's initial buffer noise to ensure silent loading.

### 📜 Disclaimer
This project is for educational purposes only. It utilizes ```yt-dlp ``` and ```ytmusicapi``` to stream content. Please respect copyright laws and the Terms of Service of content providers.
