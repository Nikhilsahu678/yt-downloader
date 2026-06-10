import os
import json
import uuid
import threading
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
import yt_dlp

app = Flask(__name__)
downloads = {}

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
                'speed': round(speed / 1024 / 1024, 2) if speed else 0,
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
        }

        if options.get('speed_limit'):
            ydl_opts['ratelimit'] = options['speed_limit'] * 1024

        if options.get('subtitles'):
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitleslangs'] = ['en']

        if options.get('audio_only'):
            ydl_opts['format'] = 'bestaudio/best'
            audio_fmt = options.get('audio_format', 'mp3')
            if audio_fmt in ('mp3', 'mp3_320'):
                quality = '320' if audio_fmt == 'mp3_320' else '192'
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': quality},
                    {'key': 'EmbedThumbnail'}
                ]
                ydl_opts['writethumbnail'] = True
            elif audio_fmt == 'm4a':
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}
                ]
            else:
                ydl_opts['postprocessors'] = [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                    {'key': 'EmbedThumbnail'}
                ]
                ydl_opts['writethumbnail'] = True
        else:
            fmt = options.get('format', 'bestvideo+bestaudio/best')
            ydl_opts['format'] = fmt
            container = options.get('format_ext', 'mp4')
            ydl_opts['merge_output_format'] = container if container in ('mp4', 'mkv', 'webm') else 'mp4'

        # playlist selected indexes
        selected_indexes = options.get('selected_indexes')
        if selected_indexes and options.get('playlist'):
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl_flat:
                info_flat = ydl_flat.extract_info(url, download=False)
            all_entries = info_flat.get('entries', [])
            selected = [all_entries[i] for i in selected_indexes if i < len(all_entries)]

            single_opts = ydl_opts.copy()
            single_opts.pop('noplaylist', None)
            single_opts['noplaylist'] = True
            single_opts['outtmpl'] = f'downloads/{download_id}/%(title)s/%(title)s.%(ext)s'
            os.makedirs(f'downloads/{download_id}', exist_ok=True)

            total = len(selected)
            status['video_count'] = total
            for idx, entry in enumerate(selected):
                video_url = entry.get('url') or entry.get('webpage_url') or f"https://youtube.com/watch?v={entry['id']}"
                status['status'] = 'downloading'
                with yt_dlp.YoutubeDL(single_opts) as ydl_single:
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

        # batch mode
        batch_urls = options.get('batch_urls')
        if batch_urls:
            single_opts = ydl_opts.copy()
            single_opts.pop('noplaylist', None)
            single_opts['noplaylist'] = True
            single_opts['outtmpl'] = f'downloads/{download_id}/batch/%(title)s.%(ext)s'
            os.makedirs(f'downloads/{download_id}/batch', exist_ok=True)

            total = len(batch_urls)
            status['queue_items'] = [{'url': u, 'percent': 0} for u in batch_urls]
            for idx, u in enumerate(batch_urls):
                u = u.strip()
                if not u:
                    continue
                status['queue_items'][idx]['status'] = 'downloading'
                with yt_dlp.YoutubeDL(single_opts) as ydl_single:
                    ydl_single.download([u])
                status['queue_items'][idx]['percent'] = 100
                status['percent'] = round((idx + 1) / total * 100, 1)
            status['filename'] = f'{total} batch files'
            status['status'] = 'done'
            return

        # single video / full playlist
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
                first_entry = entries[0]
                original_path = ydl.prepare_filename(first_entry)
                final_ext = options.get('audio_format', 'mp3')
                if final_ext == 'mp3_320':
                    final_ext = 'mp3'
                elif final_ext == 'm4a':
                    final_ext = 'm4a'
                else:
                    final_ext = 'mp3'
                final_path = original_path.rsplit('.', 1)[0] + '.' + final_ext
                status['filename'] = os.path.basename(final_path)
            else:
                final_path = ydl.prepare_filename(info)
                status['filename'] = os.path.basename(final_path)

        # conversion (without -y flag)
        convert_to = options.get('convert_to')
        if convert_to:
            filepath = os.path.join(f'downloads/{download_id}', status['filename'])
            new_name = os.path.splitext(status['filename'])[0] + '.' + convert_to
            new_path = os.path.join(f'downloads/{download_id}', new_name)
            subprocess.run(['ffmpeg', '-i', filepath, new_path], check=True)
            os.remove(filepath)
            status['filename'] = new_name

        # subtitles collection
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

# -------------------- Routes (unchanged) --------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL missing'}), 400
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl_flat:
            info_flat = ydl_flat.extract_info(url, download=False)
        is_playlist = 'entries' in info_flat
        if is_playlist:
            with yt_dlp.YoutubeDL({'quiet': True, 'playlistend': 5}) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = [e for e in info.get('entries', []) if e]
            total = info.get('playlist_count', len(entries))
            thumbs = [e.get('thumbnail') for e in entries[:4] if e.get('thumbnail')]
            return jsonify({
                'type': 'playlist',
                'title': info.get('title', 'Playlist'),
                'video_count': total,
                'thumbnails': thumbs,
                'entries': [{'title': e.get('title', 'Untitled'), 'thumbnail': e.get('thumbnail')} for e in entries]
            })
        else:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
            video_id = info.get('id', '')
            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('height'):
                    formats.append({
                        'id': f['format_id'],
                        'resolution': f'{f["height"]}p',
                        'ext': f.get('ext', 'mp4'),
                        'filesize': f.get('filesize') or f.get('filesize_approx')
                    })
            is_yt = 'youtube.com' in url or 'youtu.be' in url
            return jsonify({
                'type': 'video',
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'formats': formats,
                'video_id': video_id,
                'is_youtube': is_yt
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url', '')
    type_ = data.get('type', 'video')
    quality = data.get('quality', 'best')
    trim_start = data.get('trim_start')
    trim_end = data.get('trim_end')
    playlist = data.get('playlist', False)
    format_ext = data.get('format_ext', 'mp4')
    audio_format = data.get('audio_format', 'mp3')
    selected_indexes = data.get('selected_indexes')
    speed_limit = data.get('speed_limit')
    subtitles = data.get('subtitles', False)
    convert_to = data.get('convert_to')
    batch_urls = data.get('batch_urls')
    custom_filename = data.get('custom_filename')
    scheduled_time = data.get('scheduled_time')

    download_id = str(uuid.uuid4())
    downloads[download_id] = {'status': 'starting', 'percent': 0, 'speed': 0, 'eta': 0}

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
                height = int(quality.replace('p', ''))
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
        except:
            pass

    thread = threading.Thread(target=download_worker, args=(download_id, url, options))
    thread.daemon = True
    thread.start()
    return jsonify({'download_id': download_id})

@app.route('/api/progress/<download_id>')
def progress(download_id):
    status = downloads.get(download_id)
    if not status:
        return jsonify({'status': 'not_found'}), 404
    resp = {k: v for k, v in status.items() if k != 'trim'}
    resp['speed_history'] = status.get('speed_history', [])
    resp['subtitles'] = status.get('subtitles', [])
    return jsonify(resp)

@app.route('/file/<download_id>/<path:filename>')
def get_file(download_id, filename):
    directory = os.path.join('downloads', download_id)
    return send_from_directory(directory, filename, as_attachment=True)

if __name__ == '__main__':
    os.makedirs('downloads', exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
