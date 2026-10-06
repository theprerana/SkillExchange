try:
    import eventlet
    eventlet.monkey_patch()
    async_mode = "eventlet"
except ImportError:
    async_mode = "threading"

from flask import Flask, render_template, request, redirect, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from datetime import datetime
import sqlite3
import uuid
import firebase_admin
from firebase_admin import credentials, auth

app = Flask(__name__)
app.secret_key = "skill_exchange_secret"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)

# Active video calls stored in memory for the current server session.
active_calls = {}

# Firebase Admin SDK
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("firebase-service-account.json")
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print("Firebase service account initialization warning:", e)
        firebase_admin.initialize_app(options={'projectId': 'skill-exchange-1b00a'})



# Database connection
def get_db_connection():
    conn = sqlite3.connect('skillexchange.db', timeout=15)
    conn.row_factory = sqlite3.Row
    return conn



# Create tables
conn = get_db_connection()
cursor = conn.cursor()

try:
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
except sqlite3.OperationalError:
    pass

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

try:
    cursor.execute("""
        ALTER TABLE messages
        ADD COLUMN created_at TEXT DEFAULT ''
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
    data = request.get_json() or {}
    id_token = data.get('id_token')
    name = (data.get('name') or '').strip()
    roll_no = (data.get('roll_no') or '').strip()
    department = (data.get('department') or '').strip()
    year = data.get('year')

    if not id_token:
        return {"success": False, "message": "Firebase ID token is missing."}

    try:
        decoded_token = auth.verify_id_token(id_token, clock_skew_seconds=60)
        firebase_uid = decoded_token['uid']
        email = decoded_token.get('email')
    except Exception as e:
        print("Firebase registration error:", e)
        return {"success": False, "message": f"Invalid Firebase authentication: {str(e)}"}

    if not name or not roll_no or not email:
        return {"success": False, "message": "Required student information is missing."}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Upsert student profile: if email exists, update the profile; otherwise insert new
        cursor.execute(
            '''
            INSERT INTO students (firebase_uid, name, roll_no, email, department, year)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                firebase_uid = excluded.firebase_uid,
                name = excluded.name,
                roll_no = excluded.roll_no,
                department = excluded.department,
                year = excluded.year
            ''',
            (firebase_uid, name, roll_no, email, department, year)
        )
        conn.commit()

        # Update session if student is registering
        cursor.execute('SELECT * FROM students WHERE email=?', (email,))
        saved_student = cursor.fetchone()
        if saved_student:
            session['student_id'] = saved_student['id']
            session['name'] = saved_student['name']
            session['firebase_uid'] = firebase_uid
            session['email'] = saved_student['email']

        return {"success": True, "message": "Student profile saved successfully."}

    except Exception as e:
        print("Database save error:", e)
        return {"success": False, "message": f"Failed to save student profile: {str(e)}"}
    finally:
        conn.close()

# ============================================================
# FIREBASE LOGIN
# ============================================================

@app.route('/firebase-login', methods=['POST'])
def firebase_login():
    data = request.get_json() or {}
    id_token = data.get('id_token')

    if not id_token:
        return {"success": False, "message": "Firebase ID token missing."}

    try:
        # Verify the Firebase ID token (with 60s tolerance for machine clock variance)
        decoded_token = auth.verify_id_token(id_token, clock_skew_seconds=60)
        firebase_uid = decoded_token['uid']
        email = decoded_token.get('email')

        # Check email verification
        email_verified = decoded_token.get('email_verified', False)
        if not email_verified:
            try:
                firebase_user = auth.get_user(firebase_uid)
                email_verified = getattr(firebase_user, 'email_verified', False)
            except Exception:
                pass

        if not email_verified:
            return {"success": False, "message": "Please verify your email before logging in."}

        # Find student in SQLite by firebase_uid
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM students WHERE firebase_uid=?', (firebase_uid,))
        student = cursor.fetchone()

        # If not found by firebase_uid, check if student exists with matching email
        if not student and email:
            cursor.execute('SELECT * FROM students WHERE LOWER(email)=LOWER(?)', (email,))
            student = cursor.fetchone()
            if student:
                cursor.execute('UPDATE students SET firebase_uid=? WHERE id=?', (firebase_uid, student['id']))
                conn.commit()

        # If student still does not exist, create profile cleanly
        if not student and email:
            display_name = decoded_token.get('name') or email.split('@')[0]
            cursor.execute(
                '''
                INSERT INTO students (firebase_uid, name, roll_no, email, department, year)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    firebase_uid = excluded.firebase_uid
                ''',
                (firebase_uid, display_name, "N/A", email, "General", 1)
            )
            conn.commit()
            cursor.execute('SELECT * FROM students WHERE firebase_uid=?', (firebase_uid,))
            student = cursor.fetchone()

        conn.close()

        if not student:
            return {"success": False, "message": "Student profile not found."}

        # Create Flask session
        session['student_id'] = student['id']
        session['name'] = student['name']
        session['firebase_uid'] = firebase_uid
        session['email'] = student['email']
        session['is_verified'] = email_verified

        return {"success": True, "message": "Login successful."}

    except Exception as e:
        print("Firebase login error:", e)
        return {"success": False, "message": f"Invalid Firebase authentication: {str(e)}"}


# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM students WHERE id=?', (session['student_id'],))
    student = cursor.fetchone()

    cursor.execute('''
        SELECT * FROM skills WHERE student_id=? AND skill_type='Teach'
    ''', (session['student_id'],))
    teach_skills = cursor.fetchall()

    cursor.execute('''
        SELECT * FROM skills WHERE student_id=? AND skill_type='Learn'
    ''', (session['student_id'],))
    learn_skills = cursor.fetchall()

    conn.close()

    is_verified = session.get('is_verified', True)

    return render_template(
        'dashboard.html',
        name=student['name'] if student else session.get('name', 'Student'),
        student=student,
        teach_skills=teach_skills,
        learn_skills=learn_skills,
        is_verified=is_verified
    )


# Profile
@app.route('/profile')
def profile():
    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM students WHERE id=?', (session['student_id'],))
    student = cursor.fetchone()

    cursor.execute('''
        SELECT * FROM skills WHERE student_id=? AND skill_type='Teach'
    ''', (session['student_id'],))
    teach_skills = cursor.fetchall()

    cursor.execute('''
        SELECT * FROM skills WHERE student_id=? AND skill_type='Learn'
    ''', (session['student_id'],))
    learn_skills = cursor.fetchall()

    conn.close()

    is_verified = session.get('is_verified', True)

    return render_template(
        'profile.html',
        student=student,
        teach_skills=teach_skills,
        learn_skills=learn_skills,
        is_verified=is_verified
    )


# Edit Profile
@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        roll_no = request.form.get('roll_no', '').strip()
        department = request.form.get('department', '').strip()
        year = request.form.get('year', '').strip()

        if name:
            cursor.execute('''
                UPDATE students
                SET name=?, roll_no=?, department=?, year=?
                WHERE id=?
            ''', (name, roll_no, department, year, session['student_id']))
            conn.commit()
            session['name'] = name

        conn.close()
        return redirect('/profile')

    cursor.execute('SELECT * FROM students WHERE id=?', (session['student_id'],))
    student = cursor.fetchone()
    conn.close()

    return render_template('edit_profile.html', student=student)


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

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        teach_skills = request.form.getlist('teach_skills')
        learn_skills = request.form.getlist('learn_skills')

        # Support custom typed skills from input fields
        teach_custom = request.form.get('teach_custom', '').strip()
        if teach_custom:
            for item in teach_custom.split(','):
                cleaned = item.strip()
                if cleaned and cleaned not in teach_skills:
                    teach_skills.append(cleaned)

        learn_custom = request.form.get('learn_custom', '').strip()
        if learn_custom:
            for item in learn_custom.split(','):
                cleaned = item.strip()
                if cleaned and cleaned not in learn_skills:
                    learn_skills.append(cleaned)

        for skill in teach_skills:
            skill = skill.strip()
            if skill:
                cursor.execute('''
                    SELECT id FROM skills
                    WHERE student_id=? AND LOWER(skill_name)=LOWER(?) AND skill_type='Teach'
                ''', (session['student_id'], skill))
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO skills(student_id, skill_name, skill_type)
                        VALUES(?,?,?)
                    ''', (session['student_id'], skill, 'Teach'))

        for skill in learn_skills:
            skill = skill.strip()
            if skill:
                cursor.execute('''
                    SELECT id FROM skills
                    WHERE student_id=? AND LOWER(skill_name)=LOWER(?) AND skill_type='Learn'
                ''', (session['student_id'], skill))
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO skills(student_id, skill_name, skill_type)
                        VALUES(?,?,?)
                    ''', (session['student_id'], skill, 'Learn'))

        conn.commit()
        conn.close()
        return redirect('/dashboard')

    # Fetch currently saved skills so user can see them
    cursor.execute('''
        SELECT * FROM skills WHERE student_id=? AND skill_type='Teach'
    ''', (session['student_id'],))
    teach_skills = cursor.fetchall()

    cursor.execute('''
        SELECT * FROM skills WHERE student_id=? AND skill_type='Learn'
    ''', (session['student_id'],))
    learn_skills = cursor.fetchall()

    conn.close()
    return render_template('add_skill.html', teach_skills=teach_skills, learn_skills=learn_skills)


# Edit / Update Skill
@app.route('/edit_skill/<int:id>', methods=['POST'])
def edit_skill(id):
    if 'student_id' not in session:
        return redirect('/login')

    skill_name = request.form.get('skill_name', '').strip()
    skill_type = request.form.get('skill_type', '').strip()

    if skill_name:
        conn = get_db_connection()
        cursor = conn.cursor()
        if skill_type in ['Teach', 'Learn']:
            cursor.execute('''
                UPDATE skills
                SET skill_name=?, skill_type=?
                WHERE id=? AND student_id=?
            ''', (skill_name, skill_type, id, session['student_id']))
        else:
            cursor.execute('''
                UPDATE skills
                SET skill_name=?
                WHERE id=? AND student_id=?
            ''', (skill_name, id, session['student_id']))
        conn.commit()
        conn.close()

    return redirect(request.referrer or '/dashboard')


# Delete Skill
@app.route('/delete_skill/<int:id>', methods=['POST'])
def delete_skill(id):
    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM skills WHERE id=? AND student_id=?', (id, session['student_id']))
    conn.commit()
    conn.close()
    return redirect(request.referrer or '/dashboard')


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
@app.route('/chat')
def chat_home():
    if 'student_id' not in session:
        return redirect('/login')

    my_id = session['student_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT DISTINCT s.id
        FROM exchange_requests er
        JOIN students s ON (s.id = CASE WHEN er.sender_id = :my_id THEN er.receiver_id ELSE er.sender_id END)
        WHERE (er.sender_id = :my_id OR er.receiver_id = :my_id)
          AND er.status = 'Accepted'
        LIMIT 1
        ''',
        {"my_id": my_id}
    )
    first_conn = cursor.fetchone()
    conn.close()

    if first_conn:
        return redirect(f"/chat/{first_conn['id']}")
    return redirect('/connect')


@app.route('/api/send-message', methods=['POST'])
def api_send_message():
    if 'student_id' not in session:
        return {"success": False, "message": "Unauthorized"}, 401

    data = request.get_json() or {}
    receiver_id = data.get('receiver_id')
    message_text = (data.get('message') or '').strip()

    if not receiver_id or not message_text:
        return {"success": False, "message": "Missing message or receiver"}, 400

    try:
        receiver_id = int(receiver_id)
    except (ValueError, TypeError):
        return {"success": False, "message": "Invalid receiver ID"}, 400

    sender_id = session['student_id']
    client_time = (data.get('created_at') or '').strip()
    now_time = client_time if client_time else datetime.now().strftime("%I:%M %p")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO messages (sender_id, receiver_id, message, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        (sender_id, receiver_id, message_text, now_time)
    )
    msg_id = cursor.lastrowid
    conn.commit()
    conn.close()

    payload = {
        'id': msg_id,
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'message': message_text,
        'created_at': now_time
    }

    socketio.emit('receive_message', payload, to=f"student_{receiver_id}")
    return {"success": True, "data": payload}


@app.route('/chat/<int:id>', methods=['GET', 'POST'])
def chat(id):
    if 'student_id' not in session:
        return redirect('/login')

    my_id = session['student_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    # Send message (fallback form POST)
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        client_time = (request.form.get('created_at') or '').strip()
        now_time = client_time if client_time else datetime.now().strftime("%I:%M %p")
        if message:
            cursor.execute(
                '''
                INSERT INTO messages(sender_id, receiver_id, message, created_at)
                VALUES(?,?,?,?)
                ''',
                (my_id, id, message, now_time)
            )
            conn.commit()

    # Receiver details
    cursor.execute('SELECT * FROM students WHERE id=?', (id,))
    receiver = cursor.fetchone()

    # Current student details
    cursor.execute('SELECT * FROM students WHERE id=?', (my_id,))
    current_student = cursor.fetchone()

    # Fetch all messages between both users
    cursor.execute(
        '''
        SELECT *
        FROM messages
        WHERE (sender_id=? AND receiver_id=?)
           OR (sender_id=? AND receiver_id=?)
        ORDER BY id ASC
        ''',
        (my_id, id, id, my_id)
    )
    raw_messages = cursor.fetchall()
    messages = []
    for m in raw_messages:
        m_dict = dict(m)
        if not m_dict.get('created_at'):
            m_dict['created_at'] = now_time
        messages.append(m_dict)

    # Fetch all accepted connections for contacts sidebar
    cursor.execute(
        '''
        SELECT DISTINCT
            s.id,
            s.name,
            s.department,
            s.year,
            (SELECT message FROM messages
             WHERE (sender_id = s.id AND receiver_id = :my_id)
                OR (sender_id = :my_id AND receiver_id = s.id)
             ORDER BY id DESC LIMIT 1) AS last_message,
            (SELECT created_at FROM messages
             WHERE (sender_id = s.id AND receiver_id = :my_id)
                OR (sender_id = :my_id AND receiver_id = s.id)
             ORDER BY id DESC LIMIT 1) AS last_time
        FROM exchange_requests er
        JOIN students s ON (s.id = CASE WHEN er.sender_id = :my_id THEN er.receiver_id ELSE er.sender_id END)
        WHERE (er.sender_id = :my_id OR er.receiver_id = :my_id)
          AND er.status = 'Accepted'
        ''',
        {"my_id": my_id}
    )
    contacts = [dict(c) for c in cursor.fetchall()]

    conn.close()

    # Create a consistent Jitsi room for these two students.
    user1 = min(my_id, id)
    user2 = max(my_id, id)
    room_name = f"SkillExchange-{user1}-{user2}"

    return render_template(
        'chat.html',
        messages=messages,
        receiver=receiver,
        receiver_id=id,
        current_student=current_student,
        contacts=contacts,
        connections=contacts,
        room_name=room_name
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
        try:
            join_room(f"student_{int(student_id)}")
            print(f"Student {student_id} connected to Socket.IO")
        except (ValueError, TypeError):
            pass


@socketio.on('register_student')
def handle_register_student(data):
    """Explicitly register student into private room for instant signaling."""
    student_id = data.get('student_id') if data else None
    if not student_id:
        student_id = session.get('student_id')
    if student_id:
        try:
            join_room(f"student_{int(student_id)}")
            print(f"Student {student_id} registered into room student_{student_id}")
        except (ValueError, TypeError):
            pass


@socketio.on('send_chat_message')
def handle_send_chat_message(data):
    """Handle instant WhatsApp-style real-time chat messaging."""
    sender_id = data.get('sender_id') if data else None
    if not sender_id:
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
    try:
        student_id = int(student_id)
    except (ValueError, TypeError):
        return

    for call_id, call in list(active_calls.items()):
        if call['caller_id'] == student_id and call['status'] == 'ringing':
            emit('call_rejected', {'call_id': call_id}, to=f"student_{call['receiver_id']}")
            del active_calls[call_id]
        elif call['receiver_id'] == student_id and call['status'] == 'ringing':
            emit('call_rejected', {'call_id': call_id}, to=f"student_{call['caller_id']}")
            del active_calls[call_id]


@socketio.on('send_message')
def handle_socket_send_message(data):
    """Real-time message sending between peers."""
    sender_id = data.get('sender_id') if data else None
    if not sender_id:
        sender_id = session.get('student_id')
    receiver_id = data.get('receiver_id') if data else None
    message_text = (data.get('message') or '').strip() if data else ''

    if not sender_id or not receiver_id or not message_text:
        return

    try:
        sender_id = int(sender_id)
        receiver_id = int(receiver_id)
    except (ValueError, TypeError):
        return

    client_time = (data.get('created_at') or '').strip() if data else ''
    now_time = client_time if client_time else datetime.now().strftime("%I:%M %p")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO messages (sender_id, receiver_id, message, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        (sender_id, receiver_id, message_text, now_time)
    )
    msg_id = cursor.lastrowid
    conn.commit()
    conn.close()

    payload = {
        'id': msg_id,
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'message': message_text,
        'created_at': now_time
    }

    emit('receive_message', payload, to=f"student_{receiver_id}")
    emit('message_sent', payload)


@socketio.on('start_call')
def handle_start_call(data):
    """Caller starts ringing the selected receiver."""
    caller_id = data.get('caller_id') if data else None
    if not caller_id:
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

    # One stable room for this pair.
    user1 = min(caller_id, receiver_id)
    user2 = max(caller_id, receiver_id)
    room_name = f"SkillExchange-{user1}-{user2}"

    call_id = str(uuid.uuid4())

    # If the same caller already has a ringing call to this receiver,
    # return existing call id.
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

    # Send the ring ONLY to the receiver.
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
    """Receiver accepts and establishes peer connection."""
    call_id = data.get('call_id') if data else None

    if call_id not in active_calls:
        return

    call = active_calls[call_id]
    receiver_id = data.get('receiver_id') if data else None
    if not receiver_id:
        receiver_id = session.get('student_id')

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

    # Tell the receiver to connect too.
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
    """Receiver rejects and informs caller."""
    call_id = data.get('call_id') if data else None

    if call_id not in active_calls:
        return

    call = active_calls[call_id]
    print('CALL REJECTED:', call_id)

    emit(
        'call_rejected',
        {'call_id': call_id},
        to=f"student_{call['caller_id']}"
    )

    del active_calls[call_id]


@socketio.on('cancel_call')
def handle_cancel_call(data):
    """Caller cancels ringing before receiver answers."""
    caller_id = data.get('caller_id') if data else None
    if not caller_id:
        caller_id = session.get('student_id')
    if not caller_id:
        return
    receiver_id = data.get('receiver_id') if data else None
    for cid, call in list(active_calls.items()):
        if call['caller_id'] == caller_id:
            rec_id = call.get('receiver_id') or receiver_id
            if rec_id:
                emit('call_cancelled', {'call_id': cid}, to=f"student_{rec_id}")
            del active_calls[cid]


@socketio.on('end_call')
def handle_end_call(data):
    """Either student hangs up the video call."""
    student_id = data.get('student_id') if data else None
    if not student_id:
        student_id = session.get('student_id')
    receiver_id = data.get('receiver_id') if data else None
    if student_id:
        for cid, call in list(active_calls.items()):
            if call['caller_id'] == student_id or call['receiver_id'] == student_id:
                other_id = call['receiver_id'] if call['caller_id'] == student_id else call['caller_id']
                emit('call_ended', {'call_id': cid}, to=f"student_{other_id}")
                del active_calls[cid]
    if receiver_id and receiver_id != student_id:
        emit('call_ended', {}, to=f"student_{receiver_id}")


# ============================================================
# WEBRTC PEER-TO-PEER VIDEO CALL SIGNALING
# ============================================================

@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    """Relay WebRTC SDP offer to peer."""
    receiver_id = data.get('receiver_id') if data else None
    sender_id = data.get('sender_id') if data else None
    if not sender_id:
        sender_id = session.get('student_id')
    if receiver_id:
        emit('webrtc_offer', {
            'sender_id': sender_id,
            'offer': data.get('offer')
        }, to=f"student_{receiver_id}")


@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    """Relay WebRTC SDP answer back to caller."""
    receiver_id = data.get('receiver_id') if data else None
    sender_id = data.get('sender_id') if data else None
    if not sender_id:
        sender_id = session.get('student_id')
    if receiver_id:
        emit('webrtc_answer', {
            'sender_id': sender_id,
            'answer': data.get('answer')
        }, to=f"student_{receiver_id}")


@socketio.on('webrtc_ice_candidate')
def handle_webrtc_ice_candidate(data):
    """Relay ICE candidate to peer for NAT traversal."""
    receiver_id = data.get('receiver_id') if data else None
    sender_id = data.get('sender_id') if data else None
    if not sender_id:
        sender_id = session.get('student_id')
    if receiver_id:
        emit('webrtc_ice_candidate', {
            'sender_id': sender_id,
            'candidate': data.get('candidate')
        }, to=f"student_{receiver_id}")


if __name__ == "__main__":
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
