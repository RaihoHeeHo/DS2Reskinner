#!/usr/bin/env python3
"""Local, read-only DDS3 model/animation previewer.

Run python3 ds2_previewer.py [GAME_FOLDER_OR_ISO ...]. Rendering runs in the
system browser; all assets and game data stay on this machine.
"""
import argparse
from collections import OrderedDict
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

import dds3tool as archive
import ds2reskin as reskin
from model_preview import decode_model

ASSETS = Path(__file__).resolve().parent / 'preview'
MAX_UPLOAD = 32 * 1024 * 1024


SLOT_LABELS = {
    'ds2': {
        0: 'Idle', 1: 'Walk', 2: 'Injured', 3: 'Reserve', 4: 'Hit',
        5: 'Staggered Long', 6: 'Physical Attack', 7: 'Cast', 8: 'Cast 2',
        9: 'Lunge', 10: 'Reserve', 11: 'Concentrating', 12: 'Staggered Short',
        13: 'Summoned', 14: 'Returned', 15: 'Victory',
    },
    'nocturne': {
        0: 'Idle', 1: 'Hit', 2: 'Injured', 3: 'Physical Attack', 4: 'Cast',
        5: 'Cast 2', 7: 'Cast 3', 8: 'Physical Attack 2', 9: 'Reserve',
        10: 'Reserve', 11: 'Cast 4', 12: 'Physical Attack 3', 13: 'Idle 2',
        14: 'Negotiation (?)', 15: 'Negotiation 2 (?)',
    },
}


def source_game(game):
    # Identify the archive layout, independent of the folder/ISO filename.
    paths = game.index
    if any(p.startswith('model_lb/devil_b/') for p in paths):
        return 'ds2'
    if any(p.startswith('model/devil/0x') for p in paths):
        return 'nocturne'
    return None


class PreviewSession:
    def __init__(self, sources):
        self.token = secrets.token_urlsafe(24)
        self.entries = []
        self.models = OrderedDict()
        self.lock = threading.Lock()
        for source in dict.fromkeys(str(Path(s).resolve()) for s in sources):
            game = archive.GameSource(source)
            label = Path(source).stem
            game_id = source_game(game)
            for entry in game.files:
                p = entry.path.lower()
                if not (p.endswith('.pb') or p.endswith('.lb')):
                    continue
                if not any(x in p for x in ('devil/', 'devil_hi/', 'devil_b/', 'devil_lb/')):
                    continue
                name = ''
                try:
                    stem = Path(p).stem.removesuffix('_hi')
                    if stem.startswith('devil'):
                        stem = stem[5:]
                    ident = int(stem, 16)
                    name = reskin.noc_name(ident) if stem.startswith('0x') else reskin.ds2_name(f'{ident:03X}')
                except ValueError:
                    pass
                self.entries.append((game, entry, {'id':len(self.entries), 'source':label,
                                                    'path':entry.path, 'name':name, 'game':game_id}))
        if not self.entries:
            raise ValueError('No demon PB/LB files found in the selected game archives.')

    def model(self, index):
        if not 0 <= index < len(self.entries):
            raise ValueError('Unknown model')
        with self.lock:
            if index not in self.models:
                game, entry, info = self.entries[index]
                result = decode_model(game.read(entry), info['name'] or info['path'])
                result['game'] = info['game']
                self.models[index] = json.dumps(result, allow_nan=False, separators=(',',':')).encode()
                # Keep only a few decoded models; the archives can contain thousands.
                while len(self.models) > 3:
                    self.models.popitem(last=False)
            self.models.move_to_end(index)
            return self.models[index]


def make_server(sources):
    session = PreviewSession(sources)
    root = '/' + session.token
    assets = {'/':'index.html', '/viewer.js':'viewer.js', '/vendor/three.module.min.js':'vendor/three.module.min.js'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, data, content_type='application/json', status=200):
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def route(self):
            parsed=urlsplit(self.path)
            if not parsed.path.startswith(root+'/'):
                return None, None
            return parsed.path[len(root):], parse_qs(parsed.query)

        def do_GET(self):
            path,query=self.route()
            try:
                if path in assets:
                    suffix='application/javascript' if path.endswith('.js') else 'text/html; charset=utf-8'
                    self.reply((ASSETS/assets[path]).read_bytes(),suffix)
                elif path == '/api/slot-labels':
                    self.reply(json.dumps(SLOT_LABELS).encode())
                elif path == '/api/library':
                    self.reply(json.dumps([e[2] for e in session.entries]).encode())
                elif path == '/api/model':
                    self.reply(session.model(int(query.get('id',['-1'])[0])))
                else:
                    self.reply(b'{"error":"Not found"}',status=404)
            except (ValueError, OSError, SystemExit, IndexError) as exc:
                self.reply(json.dumps({'error':str(exc)}).encode(),status=400)
            except Exception as exc:
                self.reply(json.dumps({'error':f'Decoder error: {exc}'}).encode(),status=422)

        def do_POST(self):
            path,_=self.route()
            # Uploads must come from our own local viewer, and have a bounded size.
            origin=self.headers.get('Origin')
            expected=f'http://127.0.0.1:{self.server.server_port}'
            if path != '/api/upload' or origin != expected:
                self.reply(b'{"error":"Forbidden"}',status=403); return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0 < size <= MAX_UPLOAD:
                    raise ValueError('Choose a PB/LB file smaller than 32 MB.')
                raw=self.rfile.read(size)
                result=decode_model(raw, 'Local model')
                self.reply(json.dumps(result,allow_nan=False,separators=(',',':')).encode())
            except (ValueError, IndexError, OSError) as exc:
                self.reply(json.dumps({'error':str(exc)}).encode(),status=400)

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    server.session=session
    return server, f'http://127.0.0.1:{server.server_port}{root}/'


def launch(sources):
    server,url=make_server(sources)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    webbrowser.open(url)
    return server,url


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',nargs='*',help='Game dump folder or ISO')
    parser.add_argument('--no-browser',action='store_true',help='Print URL without opening a browser')
    args=parser.parse_args()
    sources=args.sources
    if not sources:
        downloads=Path.home()/'Downloads'
        sources=[str(downloads/name) for name in ('Nocturne','Devil Summoner 2')
                 if (downloads/name/'DDS3.DDT').is_file()]
    if not sources:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw()
        folder=filedialog.askdirectory(title='Select game folder containing DDS3.DDT and DDS3.IMG')
        root.destroy()
        if not folder:return
        sources=[folder]
    try:
        server,url=make_server(sources)
    except (ValueError,OSError,SystemExit) as exc:
        parser.exit(1,f'{exc}\n')
    print(f'Previewer: {url}\nKeep this process running. Press Ctrl+C to stop.',flush=True)
    if not args.no_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__ == '__main__':
    main()
