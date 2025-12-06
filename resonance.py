import time
import threading
import sys
import vlc
import msvcrt
import logging
import json
import os
import math 
import random 
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich.progress import Progress, BarColumn, TextColumn
from rich.table import Table
from rich.console import Console
from rich.align import Align
from rich import box 
from ytmusicapi import YTMusic
from yt_dlp import YoutubeDL

# --- SETUP LOGGING ---
logging.basicConfig(filename='debug.log', level=logging.ERROR, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURATION ---
CROSSFADE_DURATION = 5   
WARMUP_LEAD_TIME = 3     
PRELOAD_BUFFER = 25      

# --- ASSETS ---
BANNER_ART = """
██████╗ ███████╗███████╗ ██████╗ ███╗   ██╗ █████╗ ███╗   ██╗ ██████╗███████╗
██╔══██╗██╔════╝██╔════╝██╔═══██╗████╗  ██║██╔══██╗████╗  ██║██╔════╝██╔════╝
██████╔╝█████╗  ███████╗██║   ██║██╔██╗ ██║███████║██╔██╗ ██║██║     █████╗  
██╔══██╗██╔══╝  ╚════██║██║   ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██╔══╝  
██║  ██║███████╗███████║╚██████╔╝██║ ╚████║██║  ██║██║ ╚████║╚██████╗███████╗
"""

class DJDeck:
    def __init__(self, name):
        self.name = name
        # DirectSound for Windows volume separation
        self.instance = vlc.Instance('--no-video', '--quiet', '--no-audio-time-stretch', '--aout=directsound')
        self.player = self.instance.media_player_new()
        self.current_meta = None

    def load(self, url, meta):
        media = self.instance.media_new(url)
        self.player.set_media(media)
        
        # 1. Silence Guard (Paranoid Mode)
        # Prevents any audio leak during initial buffer fill
        self.player.audio_set_mute(True)
        self.player.audio_set_volume(0)
        
        self.player.play()
        
        # 2. Hammer Silence while buffering
        for _ in range(15): 
            self.player.audio_set_mute(True)
            self.player.audio_set_volume(0)
            time.sleep(0.1)
            
        # 3. Pause (Still Muted)
        self.player.set_pause(1) 
        self.current_meta = meta

    def play(self):
        self.player.set_pause(0)

    def stop(self):
        self.player.stop()

    def set_volume(self, volume):
        self.player.audio_set_volume(int(volume))

    def is_playing(self):
        return self.player.is_playing()

    def get_time(self):
        t = self.player.get_time()
        return t / 1000 if t != -1 else 0

    def get_duration(self):
        d = self.player.get_length()
        return d / 1000 if d != -1 else 1

    def seek(self, seconds):
        dur = self.get_duration()
        target = max(0, min(dur, seconds))
        self.player.set_time(int(target * 1000))

class MusicStreamer:
    def __init__(self):
        try:
            self.yt = YTMusic()
        except Exception:
            logging.error("Failed to init YTMusic", exc_info=True)
            sys.exit(1)

        self.playlist = []
        self.playlist_lock = threading.Lock() 
        
        self.deck_a = DJDeck("Deck A")
        self.deck_b = DJDeck("Deck B")
        self.active_deck = self.deck_a
        self.next_deck = self.deck_b
        
        self.running = True
        self.transitioning = False 
        self.next_deck_warmed_up = False
        self.status_msg = "Ready. 's' Search | 'i' Import"
        self.buffering_track = None 
        
        self.queue_selection_idx = 0 
        self.visual_playlist_snapshot = [] 
        
        self.mode = "NORMAL" 
        self.repeat_mode = "OFF" # OFF, ONE, ALL
        self.input_buffer = ""
        self.search_results = []
        self.selected_song_meta = None

        self.qm_thread = threading.Thread(target=self.queue_manager, daemon=True)
        self.qm_thread.start()

    def fetch_stream_url(self, video_id):
        opts = {
            'format': 'bestaudio/best', 
            'quiet': True, 
            'no_warnings': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_id, download=False)
                return info['url']
        except Exception as e:
            return None

    def background_search(self, query):
        self.status_msg = f"Searching: '{query}'..."
        try:
            results = self.yt.search(query, filter="songs")[:5]
            self.search_results = results
            if not results:
                self.status_msg = "No results found."
                self.mode = "NORMAL"
            else:
                self.status_msg = "Done."
                self.mode = "SELECTING"
        except Exception:
            self.status_msg = "Network Error."
            self.mode = "NORMAL"

    def process_import(self, filename):
        txt_path = filename if filename.endswith('.txt') else f"{filename}.txt"
        json_path = txt_path.replace('.txt', '.json')

        if not os.path.exists(txt_path):
            self.status_msg = f"Error: '{txt_path}' not found."
            self.mode = "NORMAL"
            return

        # Smart Cache Logic
        load_from_cache = False
        if os.path.exists(json_path):
            txt_mtime = os.path.getmtime(txt_path)
            json_mtime = os.path.getmtime(json_path)
            if json_mtime > txt_mtime:
                load_from_cache = True
            else:
                self.status_msg = "Playlist modified. Re-scanning..."

        if load_from_cache:
            self.status_msg = "Loading from Cache..."
            try:
                with open(json_path, 'r') as f:
                    cached_songs = json.load(f)
                    with self.playlist_lock:
                        for song in cached_songs:
                            song['url'] = None 
                            self.playlist.append(song)
                    self.status_msg = f"Imported {len(cached_songs)} songs."
                    self.mode = "NORMAL"
                    return
            except Exception:
                pass

        try:
            with open(txt_path, 'r') as f:
                lines = [line.strip() for line in f if line.strip()]
        except:
            self.status_msg = "Error reading file."
            self.mode = "NORMAL"
            return

        compiled_playlist = []
        total = len(lines)
        self.mode = "NORMAL" 
        
        for i, query in enumerate(lines):
            if self.mode == "NORMAL":
                self.status_msg = f"Importing {i+1}/{total}: {query}"
            try:
                results = self.yt.search(query, filter="songs")
                if results:
                    best = results[0]
                    meta = {
                        "title": best['title'],
                        "artist": best['artists'][0]['name'],
                        "id": best['videoId'],
                        "url": None,
                        "duration": "Unknown"
                    }
                    with self.playlist_lock:
                        self.playlist.append(meta)
                    compiled_playlist.append(meta)
                time.sleep(0.2) 
            except Exception:
                pass

        try:
            with open(json_path, 'w') as f:
                json.dump(compiled_playlist, f)
        except:
            pass
        self.status_msg = f"Import Complete ({len(compiled_playlist)} songs)."

    def queue_manager(self):
        while self.running:
            needs_loading = False
            next_song = None
            
            if not self.next_deck.current_meta:
                with self.playlist_lock:
                    if self.playlist:
                        next_song = self.playlist[0] 
                        needs_loading = True
            
            if needs_loading and next_song:
                self.buffering_track = next_song['title']
                
                if not next_song.get('url'):
                    url = self.fetch_stream_url(next_song['id'])
                    if url:
                        next_song['url'] = url
                    else:
                        with self.playlist_lock:
                            if self.playlist and self.playlist[0] == next_song:
                                self.playlist.pop(0)
                        self.buffering_track = None
                        continue 

                with self.playlist_lock:
                    if self.playlist and self.playlist[0] == next_song:
                        self.playlist.pop(0) 
                        self.next_deck.load(next_song['url'], next_song)
                
                self.buffering_track = None
            
            time.sleep(0.5)

    def play_now_action(self, video_id, meta):
        self.status_msg = f"Fetching: {meta['title']}..."
        url = self.fetch_stream_url(video_id)
        if not url:
            self.status_msg = "Error fetching stream."
            return

        meta['url'] = url
        
        with self.playlist_lock:
            if self.active_deck.current_meta:
                if self.next_deck.current_meta:
                    saved_song = self.next_deck.current_meta
                    self.playlist.insert(0, saved_song)
                    self.next_deck.stop()
                    self.next_deck.current_meta = None
                
                self.playlist.insert(0, meta)
                dur = self.active_deck.get_duration()
                if dur > 1: self.active_deck.seek(dur - 0.5)
            else:
                self.active_deck.load(url, meta)
                self.active_deck.player.audio_set_mute(False) 
                self.active_deck.set_volume(100)
                self.active_deck.play()

    def jump_to_playlist_item(self, target_idx):
        target_song = None
        with self.playlist_lock:
            has_next = self.next_deck.current_meta is not None
            if has_next and target_idx == 0:
                target_song = self.next_deck.current_meta
                dur = self.active_deck.get_duration()
                if dur > 1: self.active_deck.seek(dur - 0.5)
                return

            playlist_idx = target_idx - 1 if has_next else target_idx
            
            if 0 <= playlist_idx < len(self.playlist):
                target_song = self.playlist[playlist_idx]
                new_queue = self.playlist[playlist_idx + 1:]
                self.playlist.clear()
                self.playlist.extend(new_queue)
                
                if self.next_deck.current_meta:
                    self.next_deck.stop()
                    self.next_deck.current_meta = None

        if target_song:
            t = threading.Thread(target=self.play_now_action, args=(target_song['id'], target_song))
            t.start()
            self.queue_selection_idx = 0

    def add_to_queue_action(self, video_id, meta):
        with self.playlist_lock:
            self.playlist.append(meta)
        self.status_msg = f"Added to Queue: {meta['title']}"

    def _handle_repeat_toggle(self):
        # 1. Cycle Mode
        if self.repeat_mode == "OFF": self.repeat_mode = "ONE"
        elif self.repeat_mode == "ONE": self.repeat_mode = "ALL"
        else: self.repeat_mode = "OFF"
        
        # 2. Logic: Adjust Queue Immediately
        if not self.active_deck.current_meta: return

        with self.playlist_lock:
            # Turning ON
            if self.repeat_mode in ["ONE", "ALL"]:
                is_already_next = False
                # Check if current is already next
                if self.next_deck.current_meta and self.next_deck.current_meta['id'] == self.active_deck.current_meta['id']:
                    is_already_next = True
                elif self.playlist and self.playlist[0]['id'] == self.active_deck.current_meta['id']:
                    is_already_next = True
                
                if not is_already_next:
                    current_copy = self.active_deck.current_meta.copy()
                    current_copy['url'] = None 
                    self.playlist.insert(0, current_copy)
                    # Flush Next Deck to force reload of our repeat song
                    if self.next_deck.current_meta:
                        saved = self.next_deck.current_meta
                        self.playlist.insert(1, saved)
                        self.next_deck.stop()
                        self.next_deck.current_meta = None

            # Turning OFF
            elif self.repeat_mode == "OFF":
                # Remove next if it matches current
                if self.next_deck.current_meta and self.next_deck.current_meta['id'] == self.active_deck.current_meta['id']:
                    self.next_deck.stop()
                    self.next_deck.current_meta = None
                elif self.playlist and self.playlist[0]['id'] == self.active_deck.current_meta['id']:
                    self.playlist.pop(0)

    def handle_input(self):
        if msvcrt.kbhit():
            try:
                char = msvcrt.getwch()
            except:
                return

            if self.mode == "NORMAL":
                if char == 'q': self.running = False
                elif char == 'p': self.active_deck.player.set_pause(1)
                elif char == 'r': self.active_deck.player.set_pause(0)
                elif char == 's': 
                    self.mode = "TYPING"
                    self.input_buffer = ""
                elif char == 'i': 
                    self.mode = "IMPORTING"
                    self.input_buffer = ""
                elif char == 'l': # REPEAT TOGGLE
                    self._handle_repeat_toggle()
                elif char == '\r': self.jump_to_playlist_item(self.queue_selection_idx)
                elif char == '\xe0': 
                    arrow = msvcrt.getwch()
                    curr = self.active_deck.get_time()
                    if arrow == 'K': self.active_deck.seek(curr - 5)
                    elif arrow == 'M': self.active_deck.seek(curr + 5)
                    elif arrow == 'H': self.queue_selection_idx = max(0, self.queue_selection_idx - 1)
                    elif arrow == 'P': 
                        list_len = len(self.visual_playlist_snapshot)
                        if list_len > 0: self.queue_selection_idx = min(list_len - 1, self.queue_selection_idx + 1)

            elif self.mode == "TYPING":
                if char == '\r':
                    if self.input_buffer.strip():
                        t = threading.Thread(target=self.background_search, args=(self.input_buffer,))
                        t.start()
                    else:
                        self.mode = "NORMAL"
                elif char == '\x08': self.input_buffer = self.input_buffer[:-1]
                elif char == '\x1b': self.mode = "NORMAL"
                else: self.input_buffer += char

            elif self.mode == "IMPORTING":
                if char == '\r':
                    if self.input_buffer.strip():
                        t = threading.Thread(target=self.process_import, args=(self.input_buffer,))
                        t.start()
                    else:
                        self.mode = "NORMAL"
                elif char == '\x08': self.input_buffer = self.input_buffer[:-1]
                elif char == '\x1b': self.mode = "NORMAL"
                else: self.input_buffer += char

            elif self.mode == "SELECTING":
                if char in ['1','2','3','4','5']:
                    idx = int(char) - 1
                    if idx < len(self.search_results):
                        res = self.search_results[idx]
                        self.selected_song_meta = {
                            "title": res['title'],
                            "artist": res['artists'][0]['name'],
                            "id": res['videoId']
                        }
                        self.mode = "DECIDING"
                elif char.lower() == 'c' or char == '\x1b': self.mode = "NORMAL"

            elif self.mode == "DECIDING":
                if char == '1':
                    self.add_to_queue_action(self.selected_song_meta['id'], self.selected_song_meta)
                    self.mode = "NORMAL"
                elif char == '2':
                    t = threading.Thread(target=self.play_now_action, args=(self.selected_song_meta['id'], self.selected_song_meta))
                    t.start()
                    self.mode = "NORMAL"
                elif char.lower() == 'c' or char == '\x1b': self.mode = "NORMAL"

    def crossfade_worker(self):
        self.transitioning = True
        
        # 1. Unmute Next Deck
        self.next_deck.player.audio_set_mute(False)
        self.next_deck.play()
        
        start_time = time.time()
        while self.running:
            elapsed = time.time() - start_time
            if elapsed >= CROSSFADE_DURATION:
                break
            
            progress = elapsed / CROSSFADE_DURATION
            vol_out = math.cos(progress * 0.5 * math.pi) * 100
            vol_in  = math.sin(progress * 0.5 * math.pi) * 100
            
            self.active_deck.set_volume(vol_out)
            self.next_deck.set_volume(vol_in)
            
            time.sleep(0.05)
            
        self.active_deck.set_volume(0)
        self.active_deck.stop()
        self.next_deck.set_volume(100)
        
        self.active_deck.current_meta = None
        self.active_deck, self.next_deck = self.next_deck, self.active_deck
        
        # --- REPEAT LOGIC CHECK ---
        # If we just played the song set to 'ONE', we must now turn it OFF
        # so it doesn't loop again.
        if self.repeat_mode == "ONE":
            self.repeat_mode = "OFF"
            self.status_msg = "Repeat: OFF (Auto)"
        
        # If ALL, re-queue the finished song (active_deck is already the new one, 
        # but we need to re-queue the OLD active. Since we lost ref, we can't easily.
        # But REPEAT ALL usually relies on the queue not being consumed. 
        # In our architecture, we consume the queue. 
        # So for ALL, we should re-inject the song we just started back to the END? 
        # For simplicity, 'ALL' currently acts like 'ONE' but infinite.
        elif self.repeat_mode == "ALL":
            # Re-inject current song to top of queue for infinite loop
            current_copy = self.active_deck.current_meta.copy()
            current_copy['url'] = None
            with self.playlist_lock:
                self.playlist.insert(0, current_copy)
        
        self.transitioning = False
        self.next_deck_warmed_up = False

    def check_playback_state(self):
        # 1. Startup
        if not self.active_deck.current_meta and self.next_deck.current_meta:
            self.active_deck, self.next_deck = self.next_deck, self.active_deck
            self.active_deck.player.audio_set_mute(False)
            self.active_deck.set_volume(100)
            self.active_deck.play()
            return

        # 2. Watchdog
        if not self.transitioning and self.active_deck.is_playing():
            self.active_deck.set_volume(100)

        if self.transitioning or not self.active_deck.current_meta: return 

        pos = self.active_deck.get_time()
        dur = self.active_deck.get_duration()
        if dur <= 1: return 
        remaining = dur - pos

        warmup_trigger = CROSSFADE_DURATION + WARMUP_LEAD_TIME

        # Warm Up
        if remaining <= warmup_trigger and self.next_deck.current_meta and not self.next_deck_warmed_up:
            self.next_deck.set_volume(0)
            self.next_deck.play() 
            time.sleep(0.2)
            self.next_deck_warmed_up = True

        # Transition
        if remaining <= CROSSFADE_DURATION and self.next_deck.current_meta:
            t = threading.Thread(target=self.crossfade_worker)
            t.start()

        # Failsafe End
        if remaining <= 0.1:
             self.active_deck.stop()
             self.active_deck.current_meta = None
             if self.next_deck.current_meta:
                 self.next_deck.player.audio_set_mute(False)
                 self.next_deck.set_volume(100)
                 self.next_deck.play()
                 self.active_deck, self.next_deck = self.next_deck, self.active_deck
                 self.next_deck_warmed_up = False

    def get_visualizer_panel(self):
        width = 60
        height = 6 
        blocks = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        rows = [""] * height
        
        if self.active_deck.is_playing():
            for c in range(width):
                col_height = random.randint(0, height)
                if random.random() > 0.9: col_height = height
                for r in range(height):
                    current_level = height - 1 - r
                    if current_level < col_height:
                        rows[r] += random.choice(blocks[4:]) 
                    else:
                        rows[r] += " "
        else:
            for r in range(height - 1):
                rows[r] = " " * width
            rows[height-1] = "_" * width

        viz_str = "\n".join([f"[green]{row}[/]" for row in rows])
        return Panel(Align.center(viz_str), box=box.ROUNDED, title="[Audio Visualizer]")

    def get_ui(self):
        if self.mode in ["SELECTING", "DECIDING"]: bottom_size = 12
        else: bottom_size = 3

        layout = Layout()
        layout.split_column(
            Layout(name="player", size=6),
            Layout(name="queue"),
            Layout(name="banner", size=8),
            Layout(name="viz", size=8),
            Layout(name="input", size=bottom_size)
        )
        
        if self.active_deck.current_meta:
            title = f"[bold green]{self.active_deck.current_meta['title']}[/]"
            artist = f"[cyan]{self.active_deck.current_meta['artist']}[/]"
            curr, total = self.active_deck.get_time(), self.active_deck.get_duration()
        else:
            if self.buffering_track:
                title = f"[yellow]Buffering: {self.buffering_track}...[/]"
            else:
                title = "Idle"
            artist = ""
            curr, total = 0, 1

        prog = Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed:.0f}/{task.total:.0f}s"))
        prog.add_task(f"{title} - {artist}", total=total, completed=curr)
        
        # UI: Show Repeat Mode color-coded
        r_color = "green" if self.repeat_mode == "OFF" else "yellow" if self.repeat_mode == "ONE" else "red"
        layout["player"].update(Panel(prog, title=f"Now Playing [Repeat: [{r_color}]{self.repeat_mode}[/]]"))

        table = Table(expand=True, show_header=False, box=None)
        
        self.visual_playlist_snapshot = []
        if self.next_deck.current_meta:
            self.visual_playlist_snapshot.append(self.next_deck.current_meta)
        with self.playlist_lock:
            self.visual_playlist_snapshot.extend(self.playlist)
            
        if not self.visual_playlist_snapshot: 
            table.add_row("[dim]Queue empty...[/]")
        else:
            start_idx = max(0, self.queue_selection_idx - 7) 
            visible_slice = self.visual_playlist_snapshot[start_idx : start_idx + 15]
            
            for i, s in enumerate(visible_slice):
                real_index = start_idx + i
                style = "reverse bold" if real_index == self.queue_selection_idx else ""
                marker = "►" if real_index == self.queue_selection_idx else " "
                status_note = " [dim](Ready)[/]" if real_index == 0 and self.next_deck.current_meta else ""
                table.add_row(f"{marker} {s['title']}{status_note}", style=style)
        
        layout["queue"].update(Panel(table, title="Up Next"))
        layout["banner"].update(Panel(Align.center(f"[bold green]{BANNER_ART}[/]"), box=box.ROUNDED))
        layout["viz"].update(self.get_visualizer_panel())

        if self.mode == "NORMAL":
            rep_status = f"[{r_color}]l[/]oop:{self.repeat_mode}"
            txt = f"[bold]CMD[/] | [green]p[/]ause [green]r[/]esume [green]s[/]earch [green]i[/]mport [green]q[/]uit | [cyan]↑↓[/] Nav [cyan]Enter[/] Play [cyan]←→[/] Seek {rep_status}"
            style = "green"
        elif self.mode == "TYPING":
            txt = f"[bold]SEARCH[/]: {self.input_buffer}█"
            style = "yellow"
        elif self.mode == "IMPORTING":
            txt = f"[bold]IMPORT FILE[/]: {self.input_buffer}█\n[dim](Enter name like 'playlist.txt')[/]"
            style = "magenta"
        elif self.mode == "SELECTING":
            lines = [f"[bold]{i+1}[/]. {res['title']} - {res['artists'][0]['name']}" for i, res in enumerate(self.search_results)]
            txt = "\n".join(lines) + "\n\n[yellow]Type 1-5 to Select | 'c' to Cancel[/]"
            style = "blue"
        elif self.mode == "DECIDING":
            txt = f"[bold white]Selected: {self.selected_song_meta['title']}[/]\n\n[1] Add to Queue\n[2] Play NOW\n[c] Cancel"
            style = "magenta"
        
        layout["input"].update(Panel(txt, title=f"Status: {self.status_msg}", border_style=style))
        return layout

    def run(self):
        with Live(self.get_ui(), refresh_per_second=10, screen=True) as live:
            while self.running:
                self.handle_input()
                self.check_playback_state()
                live.update(self.get_ui())
                time.sleep(0.05)
        self.deck_a.stop()
        self.deck_b.stop()

if __name__ == "__main__":
    app = MusicStreamer()
    app.run()