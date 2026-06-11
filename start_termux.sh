#!/bin/bash
echo "===================================================="
echo "   YouTube Downloader & Info Extractor (Termux)"
echo "===================================================="
echo ""

# Install required packages if missing
echo "Checking packages..."
pkg list-installed python >/dev/null 2>&1 || pkg install python -y
pkg list-installed ffmpeg >/dev/null 2>&1 || pkg install ffmpeg -y
pkg list-installed git >/dev/null 2>&1 || pkg install git -y

echo "Installing Python libraries..."
pip install flask yt-dlp --quiet 2>/dev/null
if [ $? -ne 0 ]; then
    pip install --upgrade pip --quiet 2>/dev/null
    pip install flask yt-dlp --quiet 2>/dev/null
fi

# Setup YouTube Downloader if missing
DOWNLOADER_DIR=~/yt_downloader
if [ ! -d "$DOWNLOADER_DIR" ]; then
    echo "Downloading YouTube Downloader..."
    git clone https://github.com/Nikhilsahu678/yt-downloader.git "$DOWNLOADER_DIR" --quiet
else
    echo "YouTube Downloader already exists."
fi

# Setup YouTube Info Extractor if missing
INFO_DIR=~/yt_info
if [ ! -d "$INFO_DIR" ]; then
    echo "Setting up YouTube Info Extractor..."
    mkdir -p "$INFO_DIR/templates"
    # Download info extractor app.py and index.html from GitHub
    curl -fsSL https://raw.githubusercontent.com/Nikhilsahu678/yt-downloader/main/info_app.py -o "$INFO_DIR/app.py" 2>/dev/null
    curl -fsSL https://raw.githubusercontent.com/Nikhilsahu678/yt-downloader/main/info_index.html -o "$INFO_DIR/templates/index.html" 2>/dev/null
    # Fallback if those URLs don't exist: copy from the main repo's files (if present) or create minimal
    if [ ! -f "$INFO_DIR/app.py" ]; then
        # Minimal app.py for info extractor
        cat > "$INFO_DIR/app.py" << 'EOF'
import json
from flask import Flask, render_template, request, jsonify
import yt_dlp
from urllib.parse import urlparse

app = Flask(__name__)

def is_channel_url(url):
    parsed = urlparse(url)
    path = parsed.path.lower()
    return ('/channel/' in path or '/user/' in path or path.startswith('/@') or
            '/c/' in path and not '/watch' in url and not '/playlist' in url)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/extract', methods=['POST'])
def extract_info():
    data = request.json
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL missing'}), 400
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': False, 'skip_download': True, 'ignoreerrors': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info is None:
            return jsonify({'error': 'Could not extract info'}), 400
        if 'formats' in info and info.get('id'):
            formats = []
            for f in info.get('formats',[]):
                if f.get('vcodec')!='none' and f.get('acodec')!='none':
                    formats.append({
                        'resolution': f'{f.get("height","?")}p', 'ext': f.get('ext',''),
                        'filesize': f.get('filesize') or f.get('filesize_approx','N/A'),
                        'format_note': f.get('format_note',''), 'tbr': f.get('tbr','?')
                    })
            vid = {
                'type': 'video','id': info.get('id',''),'title': info.get('title',''),
                'description': info.get('description','')[:1000],'duration': info.get('duration',0),
                'view_count': info.get('view_count',0),'like_count': info.get('like_count','N/A'),
                'comment_count': info.get('comment_count','N/A'),'upload_date': info.get('upload_date',''),
                'channel_name': info.get('channel', info.get('uploader','Unknown')),
                'channel_handle': info.get('uploader_id',''),'channel_id': info.get('channel_id',''),
                'channel_url': info.get('channel_url',''),'tags': info.get('tags',[]),
                'categories': info.get('categories',[]),'thumbnail': info.get('thumbnail',''),
                'formats': formats,'average_rating': info.get('average_rating','N/A'),
                'age_limit': info.get('age_limit',0),'is_live': info.get('is_live',False),
                'subtitles': list(info.get('subtitles',{}).keys()) if info.get('subtitles') else [],
                'automatic_captions': list(info.get('automatic_captions',{}).keys()) if info.get('automatic_captions') else [],
            }
            return jsonify(vid)
        entries = info.get('entries', [])
        if not entries:
            return jsonify({
                'type': 'channel','channel_name': info.get('channel', info.get('uploader', info.get('title',''))),
                'channel_handle': info.get('uploader_id',''),'channel_id': info.get('channel_id', info.get('id','')),
                'description': info.get('description','')[:1000],'subscriber_count': info.get('channel_follower_count', info.get('subscriber_count','N/A')),
                'total_videos': info.get('total_videos', 0),'view_count': info.get('view_count','N/A'),
                'thumbnails': info.get('thumbnails',[]),'channel_url': info.get('channel_url', info.get('webpage_url', url)),
                'recent_videos': []
            })
        if is_channel_url(url) or ('channel_id' in info and 'playlist_id' not in info):
            recent = [{'title': e.get('title','Untitled'),'id': e.get('id',''),'url': f'https://youtube.com/watch?v={e.get("id","")}'} for e in entries[:5]]
            return jsonify({
                'type': 'channel','channel_name': info.get('channel', info.get('uploader', info.get('title',''))),
                'channel_handle': info.get('uploader_id',''),'channel_id': info.get('channel_id',''),
                'description': info.get('description','')[:1000],'subscriber_count': info.get('channel_follower_count', info.get('subscriber_count','N/A')),
                'total_videos': info.get('total_videos', len(entries)),'view_count': info.get('view_count','N/A'),
                'thumbnails': info.get('thumbnails',[]),'channel_url': info.get('channel_url', info.get('webpage_url', url)),
                'recent_videos': recent
            })
        pl = {
            'type': 'playlist','title': info.get('title',''),
            'channel_name': info.get('uploader', info.get('channel','')),'channel_handle': info.get('uploader_id',''),
            'channel_id': info.get('channel_id',''),'video_count': len(entries),'view_count': info.get('view_count',0),
            'description': info.get('description','')[:500],'entries': []
        }
        for e in entries[:5]:
            pl['entries'].append({'title': e.get('title','Untitled'),'id': e.get('id',''),'url': f'https://youtube.com/watch?v={e.get("id","")}', 'thumbnail': e.get('thumbnail','')})
        return jsonify(pl)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
EOF
    fi
    if [ ! -f "$INFO_DIR/templates/index.html" ]; then
        # Minimal index.html for info extractor (the same as before)
        cat > "$INFO_DIR/templates/index.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>YouTube Info Extractor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', Roboto, sans-serif; background: #0f0f0f; color: #fff; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px; }
    .container { width: 100%; max-width: 950px; background: #1a1a1a; border-radius: 20px; padding: 30px; box-shadow: 0 20px 40px rgba(0,0,0,0.5); }
    h1 { text-align: center; margin-bottom: 20px; color: #ff0000; }
    .flex-row { display: flex; gap: 10px; align-items: center; margin-bottom: 20px; }
    input, button { padding: 12px; border-radius: 8px; border: 1px solid #333; font-size: 16px; outline: none; background: #2a2a2a; color: #fff; }
    button { background: #ff0000; color: #fff; cursor: pointer; font-weight: 600; }
    button:disabled { background: #555; }
    #result { background: #222; border-radius: 12px; padding: 20px; margin-top: 20px; }
    .info-group { margin-bottom: 15px; }
    .info-label { color: #aaa; font-size: 14px; display: block; margin-bottom: 4px; }
    .info-value { font-size: 18px; word-break: break-word; }
    .format-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    .format-table th, .format-table td { padding: 8px; border: 1px solid #444; text-align: left; }
    .hidden { display: none; }
    a { color: #ff0000; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🔍 YouTube Info Extractor</h1>
    <div class="flex-row">
      <input type="text" id="urlInput" placeholder="Paste any YouTube link (video, channel, playlist)" style="flex:1;">
      <button id="extractBtn">Extract Info</button>
    </div>
    <div id="loading" class="hidden" style="text-align:center;">Loading...</div>
    <div id="result" class="hidden"></div>
  </div>
  <script>
    const urlInput = document.getElementById('urlInput');
    const extractBtn = document.getElementById('extractBtn');
    const loadingDiv = document.getElementById('loading');
    const resultDiv = document.getElementById('result');
    extractBtn.addEventListener('click', async () => {
      const url = urlInput.value.trim();
      if (!url) return alert('Please enter a URL');
      loadingDiv.classList.remove('hidden');
      resultDiv.classList.add('hidden');
      try {
        const res = await fetch('/api/extract', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ url }) });
        const data = await res.json();
        if (data.error) { resultDiv.innerHTML = `<p style="color:red;">Error: ${data.error}</p>`; }
        else { renderInfo(data); }
      } catch (e) { resultDiv.innerHTML = '<p style="color:red;">Network error</p>'; }
      loadingDiv.classList.add('hidden');
      resultDiv.classList.remove('hidden');
    });
    function renderInfo(data) {
      let html = '';
      if (data.type === 'video') {
        html += `<h2>🎥 ${escapeHtml(data.title)}</h2>`;
        html += `<div class="info-group"><span class="info-label">Channel:</span> <span class="info-value">${escapeHtml(data.channel_name)} (@${data.channel_handle})</span></div>`;
        html += `<div class="info-group"><span class="info-label">Duration:</span> <span class="info-value">${Math.floor(data.duration/60)}m ${data.duration%60}s</span></div>`;
        html += `<div class="info-group"><span class="info-label">Views:</span> <span class="info-value">${data.view_count?.toLocaleString()}</span> | Likes: ${data.like_count} | Comments: ${data.comment_count}</div>`;
        html += `<div class="info-group"><span class="info-label">Upload Date:</span> <span class="info-value">${data.upload_date}</span></div>`;
        if (data.tags.length) html += `<div class="info-group"><span class="info-label">Tags:</span> <span class="info-value">${data.tags.join(', ')}</span></div>`;
        html += `<div class="info-group"><span class="info-label">Description:</span> <p style="white-space: pre-wrap;">${escapeHtml(data.description)}</p></div>`;
        html += `<div class="info-group"><span class="info-label">Thumbnail:</span><br><img src="${data.thumbnail}" style="max-width:300px; border-radius:8px;"></div>`;
        html += `<h3>Available Formats</h3>`;
        html += `<table class="format-table"><tr><th>Quality</th><th>Extension</th><th>File Size</th><th>Bitrate</th></tr>`;
        data.formats.forEach(f => { html += `<tr><td>${f.resolution}</td><td>${f.ext}</td><td>${typeof f.filesize==='number'? (f.filesize/1048576).toFixed(1)+' MB' : f.filesize}</td><td>${f.tbr} kbps</td></tr>`; });
        html += `</table>`;
      } else if (data.type === 'channel') {
        html += `<h2>📺 ${escapeHtml(data.channel_name)} (@${data.channel_handle})</h2>`;
        html += `<div class="info-group"><span class="info-label">Subscribers:</span> <span class="info-value">${data.subscriber_count?.toLocaleString()}</span></div>`;
        html += `<div class="info-group"><span class="info-label">Total Videos:</span> <span class="info-value">${data.total_videos}</span></div>`;
        html += `<div class="info-group"><span class="info-label">Channel ID:</span> <span class="info-value">${data.channel_id}</span></div>`;
        if (data.thumbnails.length) html += `<div class="info-group"><span class="info-label">Avatar:</span><br><img src="${data.thumbnails[0]}" style="width:80px; border-radius:50%;"></div>`;
        html += `<div class="info-group"><span class="info-label">Description:</span> <p style="white-space: pre-wrap;">${escapeHtml(data.description)}</p></div>`;
        if (data.recent_videos.length) {
          html += `<h3>Recent Videos</h3>`;
          data.recent_videos.forEach(v => { html += `<div>• <a href="${v.url}" target="_blank">${escapeHtml(v.title)}</a></div>`; });
        }
      } else if (data.type === 'playlist') {
        html += `<h2>📀 ${escapeHtml(data.title)}</h2>`;
        html += `<div class="info-group"><span class="info-label">Channel:</span> <span class="info-value">${escapeHtml(data.channel_name)} (@${data.channel_handle})</span></div>`;
        html += `<div class="info-group"><span class="info-label">Videos:</span> <span class="info-value">${data.video_count}</span></div>`;
        html += `<h3>First few videos:</h3>`;
        data.entries.forEach(e => { html += `<div>• <a href="${e.url}" target="_blank">${escapeHtml(e.title)}</a></div>`; });
      }
      resultDiv.innerHTML = html;
    }
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
  </script>
</body>
</html>
EOF
    fi
    echo "Info Extractor created."
else
    echo "YouTube Info Extractor already exists."
fi

# Start both servers in background
echo "Starting Downloader on port 5000..."
cd "$DOWNLOADER_DIR" && python app.py &
sleep 2
echo "Starting Info Extractor on port 5001..."
cd "$INFO_DIR" && python app.py &

echo ""
echo "===================================================="
echo "   Both apps are running!"
echo "   Downloader:    http://localhost:5000"
echo "   Info Extractor: http://localhost:5001"
echo "===================================================="
echo "Open these URLs in your mobile browser."
echo "Press Enter to stop both servers."
read -r
kill %1 %2 2>/dev/null