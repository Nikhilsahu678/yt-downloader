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
                'description': info.get('description',''),
                'duration': info.get('duration',0),'view_count': info.get('view_count',0),
                'like_count': info.get('like_count','N/A'),'comment_count': info.get('comment_count','N/A'),
                'upload_date': info.get('upload_date',''),
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
                'description': info.get('description',''),
                'subscriber_count': info.get('channel_follower_count', info.get('subscriber_count','N/A')),
                'total_videos': info.get('total_videos', 0),'view_count': info.get('view_count','N/A'),
                'thumbnails': info.get('thumbnails',[]),'channel_url': info.get('channel_url', info.get('webpage_url', url)),
                'recent_videos': []
            })
        if is_channel_url(url) or ('channel_id' in info and 'playlist_id' not in info):
            recent = [{'title': e.get('title','Untitled'),'id': e.get('id',''),'url': f'https://youtube.com/watch?v={e.get("id","")}'} for e in entries[:5]]
            return jsonify({
                'type': 'channel','channel_name': info.get('channel', info.get('uploader', info.get('title',''))),
                'channel_handle': info.get('uploader_id',''),'channel_id': info.get('channel_id',''),
                'description': info.get('description',''),
                'subscriber_count': info.get('channel_follower_count', info.get('subscriber_count','N/A')),
                'total_videos': info.get('total_videos', len(entries)),'view_count': info.get('view_count','N/A'),
                'thumbnails': info.get('thumbnails',[]),'channel_url': info.get('channel_url', info.get('webpage_url', url)),
                'recent_videos': recent
            })
        pl = {
            'type': 'playlist','title': info.get('title',''),
            'channel_name': info.get('uploader', info.get('channel','')),'channel_handle': info.get('uploader_id',''),
            'channel_id': info.get('channel_id',''),'video_count': len(entries),'view_count': info.get('view_count',0),
            'description': info.get('description',''),'entries': []
        }
        for e in entries[:5]:
            pl['entries'].append({'title': e.get('title','Untitled'),'id': e.get('id',''),'url': f'https://youtube.com/watch?v={e.get("id","")}','thumbnail': e.get('thumbnail','')})
        return jsonify(pl)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
