import os, json, uuid, threading, subprocess, base64, tempfile
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
            speed = d.get('speed'); eta = d.get('eta')
            status.update({'status':'downloading','percent':round(percent,1),
                           'speed':round(speed/1024/1024,2) if speed else 0,
                           'eta':eta,'filename':d.get('filename','')})
            status.setdefault('speed_history',[]).append(status['speed'])
            if len(status['speed_history'])>50: status['speed_history'].pop(0)
        elif d['status']=='finished':
            status.update({'status':'processing','percent':100,'speed':0,'eta':0})
        downloads[download_id]=status
    return progress_hook

def download_worker(download_id,url,options):
    status=downloads.setdefault(download_id,{})
    status['status']='starting'; status['speed_history']=[]
    try:
        ydl_opts={'outtmpl':f'downloads/{download_id}/%(title)s.%(ext)s',
                  'progress_hooks':[progress_hook_factory(download_id)],
                  'quiet':True,'no_warnings':True,'ignoreerrors':True,
                  'nocheckcertificate':True,
                  'noplaylist':not options.get('playlist',False)}
        # cookies
        cookies_b64=os.environ.get('COOKIES','')
        if cookies_b64:
            data=base64.b64decode(cookies_b64)
            with tempfile.NamedTemporaryFile(mode='wb',suffix='.txt',delete=False) as f:
                f.write(data); f.flush(); ydl_opts['cookiefile']=f.name
        ydl_opts.setdefault('http_headers',{})['User-Agent']='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        # rest options same as before...
        if options.get('speed_limit'): ydl_opts['ratelimit']=options['speed_limit']*1024
        if options.get('subtitles'):
            ydl_opts['writesubtitles']=True; ydl_opts['writeautomaticsub']=True
            ydl_opts['subtitleslangs']=['en']
        if options.get('audio_only'):
            ydl_opts['format']='bestaudio/best'
            af=options.get('audio_format','mp3')
            if af in('mp3','mp3_320'):
                q='320' if af=='mp3_320' else '192'
                ydl_opts['postprocessors']=[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':q},{'key':'EmbedThumbnail'}]
                ydl_opts['writethumbnail']=True
            elif af=='m4a': ydl_opts['postprocessors']=[{'key':'FFmpegExtractAudio','preferredcodec':'m4a'}]
            else: ydl_opts['postprocessors']=[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'192'},{'key':'EmbedThumbnail'}]
        else:
            fmt=options.get('format','bestvideo+bestaudio/best'); ydl_opts['format']=fmt
            container=options.get('format_ext','mp4')
            ydl_opts['merge_output_format']=container if container in('mp4','mkv','webm') else 'mp4'
        # playlist selected indexes
        sel=options.get('selected_indexes')
        if sel and options.get('playlist'):
            with yt_dlp.YoutubeDL({'quiet':True,'extract_flat':True}) as ydl_flat:
                info_flat=ydl_flat.extract_info(url,download=False)
            all_entries=info_flat.get('entries',[])
            selected=[all_entries[i] for i in sel if i<len(all_entries)]
            s_opts=ydl_opts.copy(); s_opts['noplaylist']=True
            s_opts['outtmpl']=f'downloads/{download_id}/%(title)s/%(title)s.%(ext)s'
            os.makedirs(f'downloads/{download_id}',exist_ok=True)
            total=len(selected); status['video_count']=total
            for idx,entry in enumerate(selected):
                vurl=entry.get('url') or entry.get('webpage_url') or f"https://youtube.com/watch?v={entry['id']}"
                status['status']='downloading'
                with yt_dlp.YoutubeDL(s_opts) as ydl_single: ydl_single.download([vurl])
                status['percent']=round((idx+1)/total*100,1)
            status['filename']=f'{total} videos'; status['subtitles']=[]
            for root,dirs,files in os.walk(f'downloads/{download_id}'):
                for f in files:
                    if f.endswith(('.srt','.vtt')): status['subtitles'].append(os.path.relpath(os.path.join(root,f),f'downloads/{download_id}'))
            status['status']='done'; return
        # batch mode
        batch_urls=options.get('batch_urls')
        if batch_urls:
            s_opts=ydl_opts.copy(); s_opts['noplaylist']=True
            s_opts['outtmpl']=f'downloads/{download_id}/batch/%(title)s.%(ext)s'
            os.makedirs(f'downloads/{download_id}/batch',exist_ok=True)
            total=len(batch_urls); status['queue_items']=[{'url':u,'percent':0} for u in batch_urls]
            for idx,u in enumerate(batch_urls):
                u=u.strip()
                if not u: continue
                status['queue_items'][idx]['status']='downloading'
                with yt_dlp.YoutubeDL(s_opts) as ydl_single: ydl_single.download([u])
                status['queue_items'][idx]['percent']=100
                status['percent']=round((idx+1)/total*100,1)
            status['filename']=f'{total} batch files'; status['status']='done'; return
        # single/full playlist
        custom_name=options.get('custom_filename')
        if custom_name: ydl_opts['outtmpl']=f'downloads/{download_id}/{custom_name}.%(ext)s'
        os.makedirs(f'downloads/{download_id}',exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info=ydl.extract_info(url,download=True)
            if not info:
                status['status']='error'; status['message']='Failed to extract info'; return
            entries=info.get('entries') or [info]
            status['title']=info.get('title','Unknown'); status['video_count']=len(entries)
            if options.get('audio_only'):
                e0=entries[0]; opath=ydl.prepare_filename(e0)
                fext=options.get('audio_format','mp3')
                if fext=='mp3_320': fext='mp3'
                elif fext=='m4a': fext='m4a'
                else: fext='mp3'
                fpath=opath.rsplit('.',1)[0]+'.'+fext
                status['filename']=os.path.basename(fpath)
            else:
                fpath=ydl.prepare_filename(info); status['filename']=os.path.basename(fpath)
        # convert
        conv=options.get('convert_to')
        if conv:
            fp=os.path.join(f'downloads/{download_id}',status['filename'])
            nn=os.path.splitext(status['filename'])[0]+'.'+conv
            np=os.path.join(f'downloads/{download_id}',nn)
            subprocess.run(['ffmpeg','-i',fp,np],check=True)
            os.remove(fp); status['filename']=nn
        # subtitles collect
        status['subtitles']=[]
        for root,dirs,files in os.walk(f'downloads/{download_id}'):
            for f in files:
                if f.endswith(('.srt','.vtt')): status['subtitles'].append(os.path.relpath(os.path.join(root,f),f'downloads/{download_id}'))
        status['status']='done'
    except Exception as e:
        status['status']='error'; status['message']=str(e)

# routes unchanged (same as before)
@app.route('/')
def index(): return render_template('index.html')
@app.route('/api/info', methods=['POST'])
def get_info():
    data=request.json; url=data.get('url','').strip()
    if not url: return jsonify({'error':'URL missing'}),400
    try:
        with yt_dlp.YoutubeDL({'quiet':True,'extract_flat':True}) as ydl_flat:
            info_flat=ydl_flat.extract_info(url,download=False)
        if 'entries' in info_flat:
            with yt_dlp.YoutubeDL({'quiet':True,'playlistend':5}) as ydl:
                info=ydl.extract_info(url,download=False)
            entries=[e for e in info['entries'] if e]
            total=info.get('playlist_count',len(entries))
            thumbs=[e['thumbnail'] for e in entries[:4] if e.get('thumbnail')]
            return jsonify({'type':'playlist','title':info.get('title','Playlist'),'video_count':total,'thumbnails':thumbs,'entries':[{'title':e.get('title','Untitled'),'thumbnail':e.get('thumbnail')} for e in entries]})
        else:
            with yt_dlp.YoutubeDL({'quiet':True}) as ydl:
                info=ydl.extract_info(url,download=False)
            video_id=info.get('id','')
            formats=[]
            for f in info.get('formats',[]):
                if f.get('vcodec')!='none' and f.get('acodec')!='none' and f.get('height'):
                    formats.append({'id':f['format_id'],'resolution':f'{f["height"]}p','ext':f.get('ext','mp4'),'filesize':f.get('filesize') or f.get('filesize_approx')})
            is_yt='youtube.com' in url or 'youtu.be' in url
            return jsonify({'type':'video','title':info.get('title','Unknown'),'thumbnail':info.get('thumbnail',''),'duration':info.get('duration',0),'formats':formats,'video_id':video_id,'is_youtube':is_yt})
    except Exception as e: return jsonify({'error':str(e)}),400
@app.route('/api/download', methods=['POST'])
def start_download():
    data=request.json; url=data.get('url',''); type_=data.get('type','video')
    quality=data.get('quality','best'); trim_start=data.get('trim_start'); trim_end=data.get('trim_end')
    playlist=data.get('playlist',False); format_ext=data.get('format_ext','mp4'); audio_format=data.get('audio_format','mp3')
    selected_indexes=data.get('selected_indexes'); speed_limit=data.get('speed_limit'); subtitles=data.get('subtitles',False)
    convert_to=data.get('convert_to'); batch_urls=data.get('batch_urls'); custom_filename=data.get('custom_filename')
    scheduled_time=data.get('scheduled_time')
    download_id=str(uuid.uuid4()); downloads[download_id]={'status':'starting','percent':0,'speed':0,'eta':0}
    options={}
    if speed_limit: options['speed_limit']=int(speed_limit)
    if subtitles: options['subtitles']=True
    if trim_start: options['trim_start']=trim_start
    if trim_end: options['trim_end']=trim_end
    if type_ in('audio','playlist_audio'):
        options['audio_only']=True; options['audio_format']=audio_format
    elif type_ in('video','playlist_video'):
        if quality!='best':
            try:
                h=int(quality.replace('p',''))
                options['format']=f'bestvideo[height<={h}]+bestaudio/best[height<={h}]'
            except: options['format']='bestvideo+bestaudio/best'
        else: options['format']='bestvideo+bestaudio/best'
        options['format_ext']=format_ext
    if playlist:
        options['playlist']=True
        if selected_indexes: options['selected_indexes']=selected_indexes
    if batch_urls: options['batch_urls']=batch_urls
    if custom_filename: options['custom_filename']=custom_filename
    if convert_to: options['convert_to']=convert_to
    if scheduled_time:
        try:
            target=datetime.fromisoformat(scheduled_time)
            delay=(target-datetime.now()).total_seconds()
            if delay>0:
                threading.Timer(delay,download_worker,args=[download_id,url,options]).start()
                return jsonify({'download_id':download_id,'scheduled':True})
        except: pass
    thread=threading.Thread(target=download_worker,args=(download_id,url,options)); thread.daemon=True; thread.start()
    return jsonify({'download_id':download_id})
@app.route('/api/progress/<download_id>')
def progress(download_id):
    s=downloads.get(download_id)
    if not s: return jsonify({'status':'not_found'}),404
    resp={k:v for k,v in s.items() if k!='trim'}; resp['speed_history']=s.get('speed_history',[]); resp['subtitles']=s.get('subtitles',[])
    return jsonify(resp)
@app.route('/file/<download_id>/<path:filename>')
def get_file(download_id,filename):
    return send_from_directory(os.path.join('downloads',download_id),filename,as_attachment=True)
if __name__=='__main__':
    os.makedirs('downloads',exist_ok=True)
    port=int(os.environ.get('PORT',5000))
    app.run(host='0.0.0.0',port=port)