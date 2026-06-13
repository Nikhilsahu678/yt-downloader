import os, json, uuid, threading, subprocess, tempfile, logging, urllib.request, re
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
import yt_dlp

# ---------- DRM logger (hides Spotify false alarms) ----------
class NoDRMLogger(logging.Logger):
    def handle(self, record):
        if "DRM" in record.getMessage():
            return
        super().handle(record)

yt_dlp_logger = NoDRMLogger("yt-dlp")
yt_dlp_logger.addHandler(logging.StreamHandler())

app = Flask(__name__)
downloads = {}

# ---------- Progress Hook ----------
def progress_hook_factory(download_id):
    def progress_hook(d):
        status = downloads.get(download_id, {})
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            percent = (downloaded / total * 100) if total else 0
            speed = d.get('speed')
            eta = d.get('eta')
            status.update({
                'status': 'downloading',
                'percent': round(percent, 1),
                'speed': round(speed / 1048576, 2) if speed else 0,
                'eta': eta,
                'filename': d.get('filename', ''),
            })
            status.setdefault('speed_history', []).append(status['speed'])
            if len(status['speed_history']) > 50:
                status['speed_history'].pop(0)
        elif d['status'] == 'finished':
            status.update({'status': 'processing', 'percent': 100, 'speed': 0, 'eta': 0})
        downloads[download_id] = status
    return progress_hook

# ---------- Download Worker ----------
def download_worker(download_id, url, options):
    status = downloads.setdefault(download_id, {})
    status['status'] = 'starting'
    status['speed_history'] = []
    try:
        ydl_opts = {
            'outtmpl': f'downloads/{download_id}/%(title)s.%(ext)s',
            'progress_hooks': [progress_hook_factory(download_id)],
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'nocheckcertificate': True,
            'noplaylist': not options.get('playlist', False),
            'overwrites': True,                # prevents stuck downloads
            'logger': yt_dlp_logger,           # silences DRM warnings
        }

        if options.get('speed_limit'):
            ydl_opts['ratelimit'] = options['speed_limit'] * 1024
        if options.get('subtitles'):
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitleslangs'] = ['en']

        # ---------- AUDIO ----------
        if options.get('audio_only'):
            ydl_opts['format'] = 'bestaudio/best'
            af = options.get('audio_format', 'mp3')
            if af == 'mp3':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                    {'key': 'FFmpegMetadata'},
                    {'key': 'EmbedThumbnail'}
                ]
                ydl_opts['writethumbnail'] = True
            elif af == 'mp3_320':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
                    {'key': 'FFmpegMetadata'},
                    {'key': 'EmbedThumbnail'}
                ]
                ydl_opts['writethumbnail'] = True
            elif af == 'm4a':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'},
                    {'key': 'FFmpegMetadata'}
                ]
            elif af == 'wav':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'},
                    {'key': 'FFmpegMetadata'}
                ]
            elif af == 'aac':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'aac'},
                    {'key': 'FFmpegMetadata'}
                ]
            elif af == 'ogg':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'vorbis'},
                    {'key': 'FFmpegMetadata'}
                ]
            elif af == 'flac':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'flac'},
                    {'key': 'FFmpegMetadata'}
                ]
            else:
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                    {'key': 'FFmpegMetadata'},
                    {'key': 'EmbedThumbnail'}
                ]
                ydl_opts['writethumbnail'] = True
        else:
            # ---------- VIDEO ----------
            fmt = options.get('format', 'bestvideo+bestaudio/best')
            ydl_opts['format'] = fmt
            container = options.get('format_ext', 'mp4')
            if container in ('mp4', 'mkv', 'webm', 'mpeg', 'mpg', 'mov', 'avi'):
                ydl_opts['merge_output_format'] = container
            else:
                ydl_opts['merge_output_format'] = 'mp4'

        # ---------- playlist selected ----------
        sel = options.get('selected_indexes')
        if sel and options.get('playlist'):
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl_flat:
                info_flat = ydl_flat.extract_info(url, download=False)
            all_entries = info_flat.get('entries', [])
            selected = [all_entries[i] for i in sel if i < len(all_entries)]
            s_opts = ydl_opts.copy()
            s_opts['noplaylist'] = True
            s_opts['outtmpl'] = f'downloads/{download_id}/%(title)s/%(title)s.%(ext)s'
            os.makedirs(f'downloads/{download_id}', exist_ok=True)
            total = len(selected)
            status['video_count'] = total
            for idx, entry in enumerate(selected):
                video_url = entry.get('url') or entry.get('webpage_url') or f"https://youtube.com/watch?v={entry['id']}"
                status['status'] = 'downloading'
                with yt_dlp.YoutubeDL(s_opts) as ydl_single:
                    ydl_single.download([video_url])
                status['percent'] = round((idx + 1) / total * 100, 1)
            status['filename'] = f'{total} videos'
            status['subtitles'] = []
            for root, dirs, files in os.walk(f'downloads/{download_id}'):
                for f in files:
                    if f.endswith(('.srt', '.vtt')):
                        rel = os.path.relpath(os.path.join(root, f), f'downloads/{download_id}')
                        status['subtitles'].append(rel)
            status['status'] = 'done'
            return

        # ---------- batch ----------
        batch_urls = options.get('batch_urls')
        if batch_urls:
            s_opts = ydl_opts.copy()
            s_opts['noplaylist'] = True
            s_opts['outtmpl'] = f'downloads/{download_id}/batch/%(title)s.%(ext)s'
            os.makedirs(f'downloads/{download_id}/batch', exist_ok=True)
            total = len(batch_urls)
            status['queue_items'] = [{'url': u, 'percent': 0} for u in batch_urls]
            for idx, u in enumerate(batch_urls):
                u = u.strip()
                if not u: continue
                status['queue_items'][idx]['status'] = 'downloading'
                with yt_dlp.YoutubeDL(s_opts) as ydl_single:
                    ydl_single.download([u])
                status['queue_items'][idx]['percent'] = 100
                status['percent'] = round((idx + 1) / total * 100, 1)
            status['filename'] = f'{total} batch files'
            status['status'] = 'done'
            return

        # ---------- single / full playlist ----------
        custom_name = options.get('custom_filename')
        if custom_name:
            ydl_opts['outtmpl'] = f'downloads/{download_id}/{custom_name}.%(ext)s'
        os.makedirs(f'downloads/{download_id}', exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                status['status'] = 'error'
                status['message'] = 'Failed to extract info'
                return
            entries = info.get('entries') or [info]
            status['title'] = info.get('title', 'Unknown')
            status['video_count'] = len(entries)
            if options.get('audio_only'):
                e0 = entries[0]
                opath = ydl.prepare_filename(e0)
                fext = options.get('audio_format', 'mp3')
                if fext == 'mp3_320': fext = 'mp3'
                elif fext == 'wav': fext = 'wav'
                elif fext == 'aac': fext = 'aac'
                elif fext == 'ogg': fext = 'ogg'
                elif fext == 'flac': fext = 'flac'
                elif fext == 'm4a': fext = 'm4a'
                else: fext = 'mp3'
                fpath = opath.rsplit('.', 1)[0] + '.' + fext
                status['filename'] = os.path.basename(fpath)
            else:
                fpath = ydl.prepare_filename(info)
                status['filename'] = os.path.basename(fpath)

        # conversion
        convert_to = options.get('convert_to')
        if convert_to:
            filepath = os.path.join(f'downloads/{download_id}', status['filename'])
            new_name = os.path.splitext(status['filename'])[0] + '.' + convert_to
            new_path = os.path.join(f'downloads/{download_id}', new_name)
            subprocess.run(['ffmpeg', '-i', filepath, new_path], check=True)
            os.remove(filepath)
            status['filename'] = new_name

        # ========== CUSTOM METADATA (for Smart Download) ==========
        custom_title = options.get('custom_title')
        custom_artist = options.get('custom_artist')
        if custom_title or custom_artist:
            filepath = os.path.join(f'downloads/{download_id}', status['filename'])
            tmp_file = filepath + '.tmp'
            cmd = ['ffmpeg', '-y', '-i', filepath]
            if custom_title:
                cmd += ['-metadata', f'title={custom_title}']
            if custom_artist:
                cmd += ['-metadata', f'artist={custom_artist}']
            cmd += ['-c', 'copy', tmp_file]
            try:
                subprocess.run(cmd, check=True)
                os.replace(tmp_file, filepath)
            except subprocess.CalledProcessError:
                pass   # keep original metadata if ffmpeg fails

        status['subtitles'] = []
        for root, dirs, files in os.walk(f'downloads/{download_id}'):
            for f in files:
                if f.endswith(('.srt', '.vtt')):
                    rel = os.path.relpath(os.path.join(root, f), f'downloads/{download_id}')
                    status['subtitles'].append(rel)

        status['status'] = 'done'
    except Exception as e:
        status['status'] = 'error'
        status['message'] = str(e)

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url', '').strip()
    if not url: return jsonify({'error':'URL missing'}),400
    try:
        with yt_dlp.YoutubeDL({'quiet':True,'extract_flat':True}) as ydl_flat:
            info_flat = ydl_flat.extract_info(url, download=False)
        is_playlist = 'entries' in info_flat
        if is_playlist:
            with yt_dlp.YoutubeDL({'quiet':True,'playlistend':5}) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = [e for e in info['entries'] if e]
            total = info.get('playlist_count', len(entries))
            thumbs = [e['thumbnail'] for e in entries[:4] if e.get('thumbnail')]
            return jsonify({'type':'playlist','title':info.get('title','Playlist'),'video_count':total,'thumbnails':thumbs,'entries':[{'title':e.get('title','Untitled'),'thumbnail':e.get('thumbnail')} for e in entries]})
        else:
            with yt_dlp.YoutubeDL({'quiet':True}) as ydl:
                info = ydl.extract_info(url, download=False)
            video_id = info.get('id','')
            formats = []
            for f in info.get('formats',[]):
                if f.get('vcodec')!='none' and f.get('acodec')!='none' and f.get('height'):
                    formats.append({'id':f['format_id'],'resolution':f'{f["height"]}p','ext':f.get('ext','mp4'),'filesize':f.get('filesize') or f.get('filesize_approx')})
            is_yt = 'youtube.com' in url or 'youtu.be' in url
            return jsonify({'type':'video','title':info.get('title','Unknown'),'thumbnail':info.get('thumbnail',''),'duration':info.get('duration',0),'formats':formats,'video_id':video_id,'is_youtube':is_yt})
    except Exception as e: return jsonify({'error':str(e)}),400

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url','')
    type_ = data.get('type','video')
    quality = data.get('quality','best')
    trim_start = data.get('trim_start')
    trim_end = data.get('trim_end')
    playlist = data.get('playlist',False)
    format_ext = data.get('format_ext','mp4')
    audio_format = data.get('audio_format','mp3')
    selected_indexes = data.get('selected_indexes')
    speed_limit = data.get('speed_limit')
    subtitles = data.get('subtitles',False)
    convert_to = data.get('convert_to')
    batch_urls = data.get('batch_urls')
    custom_filename = data.get('custom_filename')
    scheduled_time = data.get('scheduled_time')

    download_id = str(uuid.uuid4())
    downloads[download_id] = {'status':'starting','percent':0,'speed':0,'eta':0}

    options = {}
    if speed_limit: options['speed_limit'] = int(speed_limit)
    if subtitles: options['subtitles'] = True
    if trim_start: options['trim_start'] = trim_start
    if trim_end: options['trim_end'] = trim_end

    if type_ == 'audio' or type_ == 'playlist_audio':
        options['audio_only'] = True
        options['audio_format'] = audio_format
    elif type_ == 'video' or type_ == 'playlist_video':
        if quality and quality != 'best':
            try:
                height = int(quality.replace('p',''))
                options['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'
            except:
                options['format'] = 'bestvideo+bestaudio/best'
        else:
            options['format'] = 'bestvideo+bestaudio/best'
        options['format_ext'] = format_ext
    if playlist:
        options['playlist'] = True
        if selected_indexes: options['selected_indexes'] = selected_indexes
    if batch_urls: options['batch_urls'] = batch_urls
    if custom_filename: options['custom_filename'] = custom_filename
    if convert_to: options['convert_to'] = convert_to

    if scheduled_time:
        try:
            target_dt = datetime.fromisoformat(scheduled_time)
            delay = (target_dt - datetime.now()).total_seconds()
            if delay > 0:
                threading.Timer(delay, download_worker, args=[download_id, url, options]).start()
                return jsonify({'download_id': download_id, 'scheduled': True})
        except: pass

    thread = threading.Thread(target=download_worker, args=(download_id, url, options))
    thread.daemon = True
    thread.start()
    return jsonify({'download_id': download_id})

@app.route('/api/progress/<download_id>')
def progress(download_id):
    status = downloads.get(download_id)
    if not status: return jsonify({'status':'not_found'}),404
    resp = {k:v for k,v in status.items() if k!='trim'}
    resp['speed_history'] = status.get('speed_history',[])
    resp['subtitles'] = status.get('subtitles',[])
    return jsonify(resp)

@app.route('/file/<download_id>/<path:filename>')
def get_file(download_id, filename):
    directory = os.path.join('downloads', download_id)
    return send_from_directory(directory, filename, as_attachment=True)

# ---------- LOCAL CONVERTER ----------
@app.route('/api/local/info', methods=['POST'])
def local_file_info():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    ext = os.path.splitext(file.filename)[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    file.save(tmp.name)
    tmp.close()
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', tmp.name
        ], capture_output=True, text=True)
        info = json.loads(result.stdout)
        format_name = info['format']['format_name']
        duration = float(info['format'].get('duration', 0))
        size = int(info['format'].get('size', 0))
        streams = info.get('streams', [])
        video_codec = None
        audio_codec = None
        for s in streams:
            if s['codec_type'] == 'video':
                video_codec = s.get('codec_name')
            elif s['codec_type'] == 'audio':
                audio_codec = s.get('codec_name')
        conv_id = str(uuid.uuid4())
        downloads[conv_id] = {'filepath': tmp.name, 'filename': file.filename}
        return jsonify({
            'filename': file.filename,
            'format': format_name,
            'duration': duration,
            'size': size,
            'video_codec': video_codec,
            'audio_codec': audio_codec,
            'conv_id': conv_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/local/convert', methods=['POST'])
def local_convert():
    data = request.json
    conv_id = data.get('conv_id')
    target_format = data.get('target_format')
    if not conv_id or not target_format:
        return jsonify({'error': 'Missing conv_id or target_format'}), 400
    conv = downloads.get(conv_id)
    if not conv:
        return jsonify({'error': 'File not found'}), 404
    src = conv['filepath']
    base = os.path.splitext(conv['filename'])[0]
    out_dir = tempfile.mkdtemp()
    out_name = f"{base}.{target_format}"
    out_path = os.path.join(out_dir, out_name)
    try:
        subprocess.run(['ffmpeg', '-i', src, out_path], check=True)
        out_id = str(uuid.uuid4())
        downloads[out_id] = {'filepath': out_path, 'filename': out_name}
        return jsonify({'download_id': out_id, 'filename': out_name})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': 'Conversion failed'}), 500

@app.route('/file/local/<download_id>/<filename>')
def get_local_file(download_id, filename):
    info = downloads.get(download_id)
    if not info:
        return "Not found", 404
    return send_file(info['filepath'], as_attachment=True, download_name=filename)

# ================== SMART DOWNLOAD (Spotify & YT Music) ==================
def scrape_spotify_metadata(url):
    """Extract title and artist from Spotify page without cookies."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
        # Look for <title>...</title>
        match = re.search(r'<title>(.*?)</title>', html)
        if match:
            title_text = match.group(1)
            # Typical format: "Song Name - Artist Name | Spotify"
            # Remove trailing " | Spotify" or "| Spotify"
            title_text = re.sub(r'\s*\|\s*Spotify\s*$', '', title_text).strip()
            if ' - ' in title_text:
                parts = title_text.split(' - ', 1)
                song = parts[0].strip()
                artist = parts[1].strip()
                return song, artist
    except Exception:
        pass
    return '', ''

@app.route('/api/extract_metadata', methods=['POST'])
def extract_metadata():
    data = request.json
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL missing'}), 400

    is_spotify = 'spotify.com' in url
    title = ''
    artist = ''
    thumbnail = ''

    # Try yt-dlp first (may work with cookies if present)
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
        'ignoreerrors': True,
        'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
        'logger': yt_dlp_logger,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info is None and is_spotify:
            ydl_opts['extract_flat'] = True
            with yt_dlp.YoutubeDL(ydl_opts) as ydl_flat:
                info = ydl_flat.extract_info(url, download=False)

        if info is not None:
            if is_spotify:
                if 'entries' in info:
                    entries = [e for e in info['entries'] if e]
                    if entries:
                        track = entries[0]
                        title = track.get('title', '').strip()
                        artist = track.get('uploader', track.get('artist', track.get('channel', ''))).strip()
                        thumbnail = track.get('thumbnail', '')
                else:
                    title = info.get('title', '').strip()
                    artist = info.get('uploader', info.get('artist', info.get('channel', ''))).strip()
                    thumbnail = info.get('thumbnail', '')
            else:
                title = info.get('title', '').strip()
                artist = info.get('uploader', info.get('channel', '')).strip()
                thumbnail = info.get('thumbnail', '')
    except Exception:
        pass

    # If still empty for Spotify, scrape the page
    if is_spotify and not title:
        title, artist = scrape_spotify_metadata(url)

    return jsonify({
        'title': title,
        'artist': artist,
        'thumbnail': thumbnail,
        'type': 'spotify' if is_spotify else 'youtube',
        'extracted': bool(title)
    })

@app.route('/api/smart_download', methods=['POST'])
def smart_download():
    data = request.json
    url = data.get('url', '').strip()
    title = data.get('title', '').strip()
    artist = data.get('artist', '').strip()
    audio_format = data.get('audio_format', 'mp3')
    is_spotify = 'spotify.com' in url

    if not title or not artist:
        return jsonify({'error': 'Title and artist are required'}), 400

    if is_spotify:
        queries = [
            f"{artist} - {title} Official Music Video",
            f"{artist} - {title} Official Audio",
            f"{title} {artist} official song"
        ]
        search_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best',
            'default_search': 'ytsearch',
            'skip_download': True,
            'extract_flat': False,
            'noplaylist': True,
            'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            'logger': yt_dlp_logger,
        }

        video_url = None
        for query in queries:
            try:
                with yt_dlp.YoutubeDL(search_opts) as ydl_search:
                    info = ydl_search.extract_info(f"ytsearch1:{query}", download=False)
                if info and info.get('entries'):
                    best = max(info['entries'], key=lambda e: e.get('view_count', 0))
                    video_url = best['webpage_url']
                    break
            except:
                continue

        if not video_url:
            return jsonify({'error': 'No matching official video found. Paste the YouTube URL directly in the Smart Download field.'}), 404
    else:
        video_url = url

    download_id = str(uuid.uuid4())
    downloads[download_id] = {'status': 'starting', 'percent': 0, 'speed': 0, 'eta': 0}
    options = {
        'audio_only': True,
        'audio_format': audio_format,
        'playlist': False,
        'selected_indexes': None,
        'speed_limit': None,
        'subtitles': False,
        'convert_to': None,
        'batch_urls': None,
        'custom_filename': None,
        'scheduled_time': None,
        'custom_title': title,
        'custom_artist': artist,
    }
    thread = threading.Thread(target=download_worker, args=(download_id, video_url, options))
    thread.daemon = True
    thread.start()
    return jsonify({'download_id': download_id})

if __name__ == '__main__':
    os.makedirs('downloads', exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
