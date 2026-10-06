from flask import Flask, render_template, request, redirect, session
from flask_socketio import SocketIO, emit, join_room
import sqlite3
import uuid
import firebase_admin
from firebase_admin import credentials, auth

app = Flask(__name__)
app.secret_key = "skill_exchange_secret"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Active video calls stored in memory for the current server session.
active_calls = {}

# Firebase Admin SDK
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)


# Database connection
def get_db_connection():
    conn = sqlite3.connect('skillexchange.db')
    conn.row_factory = sqlite3.Row
    return conn



# Create tables
conn = get_db_connection()
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS students(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firebase_uid TEXT UNIQUE,
    name TEXT,
    roll_no TEXT,
    email TEXT UNIQUE,
    department TEXT,
    year INTEGER
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS skills(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    skill_name TEXT,
    skill_type TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS exchange_requests(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
    receiver_id INTEGER,
    status TEXT DEFAULT 'Pending',

    FOREIGN KEY(sender_id) REFERENCES students(id),
    FOREIGN KEY(receiver_id) REFERENCES students(id)
)
''')

# Chat Messages Table
cursor.execute('''
CREATE TABLE IF NOT EXISTS messages(

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    sender_id INTEGER,

    receiver_id INTEGER,

    message TEXT,

    FOREIGN KEY(sender_id) REFERENCES students(id),

    FOREIGN KEY(receiver_id) REFERENCES students(id)

)
''')
conn.commit()

try:
    cursor.execute("""
        ALTER TABLE exchange_requests
        ADD COLUMN skill_name TEXT
    """)
    conn.commit()
except sqlite3.OperationalError:
    pass

conn.close()


# Home
@app.route('/')
def home():
    return render_template('index.html')



# REGISTER

# REGISTER

@app.route('/register', methods=['GET'])
def register():
    return render_template('register.html')


# LOGIN

@app.route('/login', methods=['GET'])
def login():
    return render_template('login.html')


# SAVE STUDENT PROFILE TO SQLITE

# SAVE STUDENT PROFILE TO SQLITE


@app.route('/save-student', methods=['POST'])
def save_student():

    data = request.get_json()

    id_token = data.get('id_token')

    name = data.get('name')
    roll_no = data.get('roll_no')
    department = data.get('department')
    year = data.get('year')

    if not id_token:
        return {
            "success": False,
            "message": "Firebase ID token is missing."
        }

    try:
        decoded_token = auth.verify_id_token(id_token)

        firebase_uid = decoded_token['uid']
        email = decoded_token.get('email')

    except Exception as e:
        print("Firebase registration error:", e)

        return {
            "success": False,
            "message": "Invalid Firebase authentication."
        }

    if not name or not roll_no or not email:
        return {
            "success": False,
            "message": "Required student information is missing."
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            '''
            INSERT INTO students
            (
                firebase_uid,
                name,
                roll_no,
                email,
                department,
                year
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                firebase_uid,
                name,
                roll_no,
                email,
                department,
                year
            )
        )

        conn.commit()

        return {
            "success": True,
            "message": "Student profile saved successfully."
        }

    except sqlite3.IntegrityError:

        return {
            "success": False,
            "message": "Email or Roll Number already exists."
        }

    except Exception as e:

        print("Database error:", e)

        return {
            "success": False,
            "message": "Failed to save student profile."
        }

    finally:
        conn.close()

# ============================================================
# FIREBASE LOGIN
# ============================================================

@app.route('/firebase-login', methods=['POST'])
def firebase_login():

    data = request.get_json()

    id_token = data.get('id_token')

    if not id_token:
        return {
            "success": False,
            "message": "Firebase ID token missing."
        }

    try:

        # Verify the Firebase ID token
        decoded_token = auth.verify_id_token(id_token)

        # Get the real Firebase UID
        firebase_uid = decoded_token['uid']

        # Get Firebase user
        firebase_user = auth.get_user(firebase_uid)

        # Check email verification
        if not firebase_user.email_verified:
            return {
                "success": False,
                "message": "Please verify your email before logging in."
            }

        # Find student in SQLite
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT *
            FROM students
            WHERE firebase_uid=?
            ''',
            (firebase_uid,)
        )

        student = cursor.fetchone()

        conn.close()

        if not student:
            return {
                "success": False,
                "message": "Student profile not found."
            }

        # Create Flask session
        session['student_id'] = student['id']
        session['name'] = student['name']
        session['firebase_uid'] = firebase_uid

        return {
            "success": True,
            "message": "Login successful."
        }

    except Exception as e:

        print("Firebase login error:", e)

        return {
            "success": False,
            "message": "Invalid Firebase authentication."
        }


# Dashboard
@app.route('/dashboard')
def dashboard():

    if 'student_id' not in session:
        return redirect('/login')

    return render_template(
        'dashboard.html',
        name=session['name']
    )



# Logout
@app.route('/logout')
def logout():

    session.clear()

    return redirect('/')


# Add Skill
@app.route('/add_skill', methods=['GET', 'POST'])
def add_skill():

    if 'student_id' not in session:
        return redirect('/login')

    if request.method == 'POST':

        teach_skills = request.form.getlist('teach_skills')
        learn_skills = request.form.getlist('learn_skills')

        conn = get_db_connection()
        cursor = conn.cursor()

        for skill in teach_skills:
            cursor.execute(
                '''
                INSERT INTO skills(student_id, skill_name, skill_type)
                VALUES(?,?,?)
                ''',
                (session['student_id'], skill, 'Teach')
            )

        for skill in learn_skills:
            cursor.execute(
                '''
                INSERT INTO skills(student_id, skill_name, skill_type)
                VALUES(?,?,?)
                ''',
                (session['student_id'], skill, 'Learn')
            )

        conn.commit()
        conn.close()

        return redirect('/dashboard')

    return render_template('add_skill.html')


# Matching Students

@app.route('/matchingstudent')
def matchingstudent():

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    # My learning skills
    cursor.execute(
        '''
        SELECT skill_name
        FROM skills
        WHERE student_id=?
        AND skill_type='Learn'
        ''',

        (session['student_id'],)
    )

    my_learn = [
        row['skill_name']
        for row in cursor.fetchall()
    ]


    # All other students
    cursor.execute(
        '''
        SELECT id,name
        FROM students
        WHERE id!=?
        ''',

        (session['student_id'],)
    )

    others = cursor.fetchall()

    matches = []


    for student in others:

        # Their teaching skills
        cursor.execute(
            '''
            SELECT skill_name
            FROM skills
            WHERE student_id=?
            AND skill_type='Teach'
            ''',

            (student['id'],)
        )

        their_teach = [
            row['skill_name']
            for row in cursor.fetchall()
        ]

        # Common skills
        common_skills = list(
            set(my_learn) &
            set(their_teach)
        )

        # Match percentage
        if common_skills:

            percentage = int(
                len(common_skills)
                /
                len(my_learn)
                * 100
            )

            matches.append({

                'id': student['id'],

                'name': student['name'],

                'skills': common_skills,

                'percentage': percentage

            })


    # Students to whom request already sent
    cursor.execute(
        '''
        SELECT receiver_id
        FROM exchange_requests
        WHERE sender_id=?
        ''',

        (session['student_id'],)
    )

    sent_requests = [

        row['receiver_id']

        for row in cursor.fetchall()

    ]


    # Highest percentage first
    matches.sort(
        key=lambda x: x['percentage'],
        reverse=True
    )

    conn.close()

    return render_template(

        'matchingstudent.html',

        matches=matches,

        sent_requests=sent_requests

    )

# Send Request
@app.route('/send_request/<int:id>', methods=['POST'])
def send_request(id):

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        '''
        SELECT *
        FROM exchange_requests
        WHERE sender_id=? AND receiver_id=?
        ''',

        (session['student_id'], id)
    )

    existing = cursor.fetchone()

    if existing:

        # If already accepted, do nothing
        if existing['status'] == 'Accepted':

            conn.close()

            return redirect('/matchingstudent')

        # Otherwise remove pending request
        cursor.execute(
            '''
            DELETE FROM exchange_requests
            WHERE sender_id=? AND receiver_id=?
            ''',

            (session['student_id'], id)
        )

    else:

        cursor.execute(
            '''
            INSERT INTO exchange_requests(
            sender_id,
            receiver_id,
            status
            )

            VALUES(?,?,?)
            ''',

            (session['student_id'], id, 'Pending')
        )

    conn.commit()
    conn.close()

    return redirect('/matchingstudent')


# View Requests
@app.route('/request')
def request_page():

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
    '''
    SELECT
    exchange_requests.id,
    students.name,
    exchange_requests.status

    FROM exchange_requests

    JOIN students
    ON students.id=exchange_requests.sender_id

    WHERE exchange_requests.receiver_id=?
    ''',

    (session['student_id'],)
    )

    requests = cursor.fetchall()

    conn.close()

    return render_template(
    'request.html',
    requests=requests
    )

# Accept Request
@app.route('/accept_request/<int:id>', methods=['POST'])
def accept_request(id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
    '''
    UPDATE exchange_requests

    SET status='Accepted'

    WHERE id=?
    ''',

    (id,)
    )

    conn.commit()
    conn.close()

    return redirect('/request')


# Reject Request
@app.route('/reject_request/<int:id>', methods=['POST'])
def reject_request(id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
    '''
    UPDATE exchange_requests

    SET status='Rejected'

    WHERE id=?
    ''',

    (id,)
    )

    conn.commit()
    conn.close()

    return redirect('/request')

# Connections
@app.route('/connect')
def connect():

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        '''
        SELECT DISTINCT
               students.id,
               students.name,
               students.email,
               students.department

        FROM exchange_requests

        JOIN students
        ON students.id = exchange_requests.sender_id

        WHERE exchange_requests.receiver_id = ?
        AND exchange_requests.status = 'Accepted'
        ''',

        (session['student_id'],)
    )

    connections = cursor.fetchall()

    conn.close()

    return render_template(
        'connect.html',
        connections=connections
    )
@app.route('/chat', methods=['GET'])
def chat_home():
    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all active connections for sidebar
    cursor.execute('''
    SELECT DISTINCT students.id, students.name, students.email, students.department
    FROM students
    JOIN exchange_requests 
    ON (
        (students.id = exchange_requests.sender_id AND exchange_requests.receiver_id = ?)
        OR
        (students.id = exchange_requests.receiver_id AND exchange_requests.sender_id = ?)
    )
    WHERE exchange_requests.status = 'Accepted'
    AND students.id != ?
    ''', (session['student_id'], session['student_id'], session['student_id']))

    connections = cursor.fetchall()
    conn.close()

    if connections:
        return redirect(f"/chat/{connections[0]['id']}")

    return render_template(
        'chat.html',
        messages=[],
        receiver=None,
        receiver_id=None,
        connections=[],
        room_name=""
    )


@app.route('/chat/<int:id>', methods=['GET', 'POST'])
def chat(id):

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get receiver info
    cursor.execute('SELECT * FROM students WHERE id=?', (id,))
    receiver = cursor.fetchone()

    # Get all active connections for sidebar
    cursor.execute('''
    SELECT DISTINCT students.id, students.name, students.email, students.department
    FROM students
    JOIN exchange_requests 
    ON (
        (students.id = exchange_requests.sender_id AND exchange_requests.receiver_id = ?)
        OR
        (students.id = exchange_requests.receiver_id AND exchange_requests.sender_id = ?)
    )
    WHERE exchange_requests.status = 'Accepted'
    AND students.id != ?
    ''', (session['student_id'], session['student_id'], session['student_id']))

    connections = cursor.fetchall()

    # Send message (HTTP POST fallback)
    if request.method == 'POST':

        message = request.form.get('message', '').strip()

        if message:
            cursor.execute(
                '''
                INSERT INTO messages(
                sender_id,
                receiver_id,
                message
                )

                VALUES(?,?,?)
                ''',

                (
                    session['student_id'],
                    id,
                    message
                )
            )

            conn.commit()


    # Fetch all messages between both users
    cursor.execute(
        '''
        SELECT *
        FROM messages

        WHERE

        (sender_id=? AND receiver_id=?)

        OR

        (sender_id=? AND receiver_id=?)

        ORDER BY id
        ''',

        (
            session['student_id'],
            id,

            id,
            session['student_id']
        )
    )

    messages = cursor.fetchall()

    conn.close()


    # Create a consistent Jitsi room for these two students.
    # Sorting the IDs ensures both users get the same room name.
    user1 = min(session['student_id'], id)
    user2 = max(session['student_id'], id)
    room_name = f"SkillExchange-{user1}-{user2}"

    return render_template(
        'chat.html',
        messages=messages,
        receiver=receiver,
        receiver_id=id,
        connections=connections,
        room_name=room_name
    )




# Profile
@app.route('/profile')
def profile():

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Student details
    cursor.execute(
        '''
        SELECT *
        FROM students
        WHERE id=?
        ''',

        (session['student_id'],)
    )

    student = cursor.fetchone()


    # Skills I Can Teach
    cursor.execute(
        '''
        SELECT skill_name
        FROM skills
        WHERE student_id=?
        AND skill_type='Teach'
        ''',

        (session['student_id'],)
    )

    teach_skills = cursor.fetchall()


    # Skills I Want To Learn
    cursor.execute(
        '''
        SELECT skill_name
        FROM skills
        WHERE student_id=?
        AND skill_type='Learn'
        ''',

        (session['student_id'],)
    )

    learn_skills = cursor.fetchall()

    conn.close()

    return render_template(
        'profile.html',

        student=student,

        teach_skills=teach_skills,

        learn_skills=learn_skills
    )




# My Skills
@app.route('/my_skills')
def my_skills():

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        '''
        SELECT skill_name, skill_type
        FROM skills
        WHERE student_id=?
        ''',
        (session['student_id'],)
    )

    skills = cursor.fetchall()

    conn.close()

    return render_template(
        'my_skills.html',
        skills=skills
    )
# Existing routes...

@app.route('/about')
def about():
    return render_template("about.html")

@app.route('/features')
def features():
    return render_template("features.html")

@app.route('/students')
def students():
    return render_template("students.html")

@app.route('/contact')
def contact():
    return render_template("contact.html")

# ============================================================
# REAL-TIME CHAT & VIDEO CALL SIGNALING (Socket.IO)
# ============================================================

@socketio.on('connect')
def handle_connect():
    """Put each logged-in student into a private Socket.IO room."""
    student_id = session.get('student_id')

    if student_id is not None:
        join_room(f"student_{student_id}")
        print(f"Student {student_id} connected to Socket.IO")


@socketio.on('send_chat_message')
def handle_send_chat_message(data):
    """Handle instant WhatsApp-style real-time chat messaging."""
    sender_id = session.get('student_id')
    receiver_id = data.get('receiver_id') if data else None
    message_text = data.get('message', '').strip() if data else ''

    if not sender_id or not receiver_id or not message_text:
        return

    try:
        sender_id = int(sender_id)
        receiver_id = int(receiver_id)
    except (TypeError, ValueError):
        return

    # Save into database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO messages(sender_id, receiver_id, message)
        VALUES(?,?,?)
        ''',
        (sender_id, receiver_id, message_text)
    )
    conn.commit()
    msg_id = cursor.lastrowid
    conn.close()

    payload = {
        'id': msg_id,
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'message': message_text
    }

    # Broadcast to receiver and sender
    emit('receive_chat_message', payload, to=f"student_{receiver_id}")
    emit('receive_chat_message', payload, to=f"student_{sender_id}")


@socketio.on('disconnect')
def handle_disconnect():
    """Clean up ringing calls if a user disconnects."""
    student_id = session.get('student_id')

    if student_id is None:
        return

    student_id = int(student_id)

    for call_id, call in list(active_calls.items()):
        if call['caller_id'] == student_id and call['status'] == 'ringing':
            emit('call_rejected', {'call_id': call_id}, to=f"student_{call['receiver_id']}")
            del active_calls[call_id]
        elif call['receiver_id'] == student_id and call['status'] == 'ringing':
            emit('call_rejected', {'call_id': call_id}, to=f"student_{call['caller_id']}")
            del active_calls[call_id]


@socketio.on('start_call')
def handle_start_call(data):
    """Caller starts ringing the selected receiver."""
    caller_id = session.get('student_id')
    receiver_id = data.get('receiver_id') if data else None

    if caller_id is None or receiver_id is None:
        return

    try:
        caller_id = int(caller_id)
        receiver_id = int(receiver_id)
    except (TypeError, ValueError):
        return

    if caller_id == receiver_id:
        return

    # One stable Jitsi room for this pair.
    user1 = min(caller_id, receiver_id)
    user2 = max(caller_id, receiver_id)
    room_name = f"SkillExchange-{user1}-{user2}"

    call_id = str(uuid.uuid4())

    # If the same caller already has a ringing call to this receiver,
    # do not create another one.
    for existing_id, existing_call in active_calls.items():
        if (existing_call['caller_id'] == caller_id and
                existing_call['receiver_id'] == receiver_id and
                existing_call['status'] == 'ringing'):
            emit('call_already_ringing', {'call_id': existing_id})
            return

    # Get caller name for the popup.
    caller_name = f"Student {caller_id}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM students WHERE id=?', (caller_id,))
    caller = cursor.fetchone()
    if caller and caller['name']:
        caller_name = caller['name']
    conn.close()

    active_calls[call_id] = {
        'caller_id': caller_id,
        'receiver_id': receiver_id,
        'room_name': room_name,
        'status': 'ringing'
    }

    print('CALL STARTED:', active_calls[call_id])

    # Send the ring ONLY to the receiver, not to every connected user.
    emit(
        'incoming_call',
        {
            'call_id': call_id,
            'caller_id': caller_id,
            'caller_name': caller_name,
            'room_name': room_name
        },
        to=f"student_{receiver_id}"
    )


@socketio.on('accept_call')
def handle_accept_call(data):
    """Receiver accepts and tells the caller to join the same Jitsi room."""
    call_id = data.get('call_id') if data else None

    if call_id not in active_calls:
        return

    call = active_calls[call_id]
    receiver_id = session.get('student_id')

    if receiver_id != call['receiver_id']:
        return

    call['status'] = 'accepted'

    print('CALL ACCEPTED:', call_id)

    # Tell the caller that the receiver accepted.
    emit(
        'call_accepted',
        {
            'call_id': call_id,
            'room_name': call['room_name']
        },
        to=f"student_{call['caller_id']}"
    )

    # Tell the receiver to open Jitsi too.
    emit(
        'call_connected',
        {
            'call_id': call_id,
            'room_name': call['room_name']
        },
        to=f"student_{call['receiver_id']}"
    )


@socketio.on('reject_call')
def handle_reject_call(data):
    """Receiver rejects and tells the caller that the call was rejected."""
    call_id = data.get('call_id') if data else None

    if call_id not in active_calls:
        return

    call = active_calls[call_id]
    receiver_id = session.get('student_id')

    if receiver_id != call['receiver_id']:
        return

    print('CALL REJECTED:', call_id)

    emit(
        'call_rejected',
        {'call_id': call_id},
        to=f"student_{call['caller_id']}"
    )

    del active_calls[call_id]


if __name__ == "__main__":
    socketio.run(app, debug=True)
