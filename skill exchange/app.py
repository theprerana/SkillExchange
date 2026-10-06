from flask import Flask, render_template, request, redirect, session
import sqlite3
import firebase_admin
from firebase_admin import credentials, auth

app = Flask(__name__)
app.secret_key = "skill_exchange_secret"

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
        decoded_token = auth.verify_id_token(id_token, clock_skew_seconds=60)

        firebase_uid = decoded_token['uid']
        email = decoded_token.get('email')

    except Exception as e:
        print("Firebase registration error:", e)

        return {
            "success": False,
            "message": f"Invalid Firebase authentication: {str(e)}"
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

        # Verify the Firebase ID token (with 60s tolerance for machine clock variance)
        decoded_token = auth.verify_id_token(id_token, clock_skew_seconds=60)

        # Get the real Firebase UID and email
        firebase_uid = decoded_token['uid']
        email = decoded_token.get('email')

        # Check email verification:
        # First check token claims (does not require private key API call)
        email_verified = decoded_token.get('email_verified', False)
        if not email_verified:
            try:
                firebase_user = auth.get_user(firebase_uid)
                email_verified = getattr(firebase_user, 'email_verified', False)
            except Exception:
                pass

        if not email_verified:
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

        # If not found by firebase_uid, check if student exists with matching email
        if not student and email:
            cursor.execute('SELECT * FROM students WHERE email=?', (email,))
            student = cursor.fetchone()
            if student:
                cursor.execute('UPDATE students SET firebase_uid=? WHERE id=?', (firebase_uid, student['id']))
                conn.commit()

        # If student still does not exist, auto-create profile from token information
        if not student and email:
            display_name = decoded_token.get('name') or email.split('@')[0]
            cursor.execute(
                '''
                INSERT INTO students (firebase_uid, name, roll_no, email, department, year)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (firebase_uid, display_name, "N/A", email, "General", 1)
            )
            conn.commit()
            cursor.execute('SELECT * FROM students WHERE firebase_uid=?', (firebase_uid,))
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
            "message": f"Invalid Firebase authentication: {str(e)}"
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
@app.route('/chat/<int:id>', methods=['GET', 'POST'])
def chat(id):

    if 'student_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Send message
    if request.method == 'POST':

        message = request.form['message']

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

    # Create a unique Jitsi room for this pair of connected students.
    # Sorting the IDs ensures both users get exactly the same room name.
    user1 = min(session['student_id'], id)
    user2 = max(session['student_id'], id)
    room_name = f"SkillExchange-{user1}-{user2}"

    return render_template(
        'chat.html',
        messages=messages,
        receiver_id=id,
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

if __name__ == "__main__":
    app.run(debug=True)
