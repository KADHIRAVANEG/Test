from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import subprocess
import os
import tempfile
import threading
import shutil

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

active_sessions = {}

def run_interactive(sid, code, language):
    try:
        # Create temporary directory
        workdir = tempfile.mkdtemp()
        
        # Write code to file
        code_path = os.path.join(workdir, "main.py")
        with open(code_path, 'w') as f:
            f.write(code)

        # Start Python process
        process = subprocess.Popen(
            ["python", "-u", "main.py"],
            cwd=workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Store session
        active_sessions[sid] = {
            'process': process,
            'workdir': workdir
        }

        # Send success message
        socketio.emit('started', {'msg': 'Interactive session started!'}, room=sid)

        # Output reader thread
        def read_output():
            try:
                # Read output line by line
                while True:
                    line = process.stdout.readline()
                    if not line:
                        if process.poll() is not None:
                            break
                        continue
                    
                    # Send output to client
                    socketio.emit('output', {'data': line}, room=sid)
                
                # Process ended
                exit_code = process.poll()
                socketio.emit('exit', {'code': exit_code}, room=sid)
                
            except Exception as e:
                socketio.emit('error', {'msg': f'Error: {str(e)}'}, room=sid)
            finally:
                # Cleanup
                if sid in active_sessions:
                    try:
                        shutil.rmtree(workdir)
                    except:
                        pass
                    del active_sessions[sid]

        # Start reader thread
        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()

    except Exception as e:
        socketio.emit('error', {'msg': f'Failed to start: {str(e)}'}, room=sid)

@socketio.on('connect')
def handle_connect():
    emit('connected', {'msg': 'Connected to Interactive Code Runner!'})

@socketio.on('start_interactive')
def handle_start(data):
    sid = request.sid
    code = data.get('code', '').strip()
    
    # Clear existing session
    if sid in active_sessions:
        try:
            session = active_sessions[sid]
            session['process'].terminate()
            shutil.rmtree(session['workdir'])
        except:
            pass
        del active_sessions[sid]
    
    run_interactive(sid, code, 'python')

@socketio.on('send_input')
def handle_input(data):
    sid = request.sid
    input_data = data.get('data', '')
    
    session = active_sessions.get(sid)
    if not session:
        emit('error', {'msg': 'No active session'})
        return
        
    process = session['process']
    if process.poll() is not None:
        emit('error', {'msg': 'Process has ended'})
        return
        
    try:
        process.stdin.write(input_data)
        process.stdin.flush()
    except Exception as e:
        emit('error', {'msg': f'Input failed: {str(e)}'})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    session = active_sessions.pop(sid, None)
    if session:
        try:
            session['process'].terminate()
            shutil.rmtree(session['workdir'])
        except:
            pass

@app.route('/')
def home():
    return jsonify({
        "status": "🚀 Interactive Code Runner",
        "sessions": len(active_sessions)
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 1000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
