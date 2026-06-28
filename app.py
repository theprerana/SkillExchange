from flask import Flask, render_template, request, redirect, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "skill_exchange_secret"


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
    name TEXT,
    roll_no TEXT,
    email TEXT UNIQUE,
    department TEXT,
    year INTEGER,
    password TEXT
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
conn.close()



# ADD THIS PART ONLY ONCE
try:

    cursor.execute("""
    ALTER TABLE exchange_requests
    ADD COLUMN skill_name TEXT
    """)

    conn.commit()

except:

    pass


conn.close()



# Home
@app.route('/')
def home():
    return render_template('index.html')



# Register
@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        name = request.form['name']
        roll_no = request.form['roll_no']
        email = request.form['email']
        department = request.form['department']
        year = request.form['year']
        password = generate_password_hash(request.form['password'])

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''
                INSERT INTO students(name, roll_no, email, department, year, password)
                VALUES(?,?,?,?,?,?)
                ''',
                (name, roll_no, email, department, year, password)
            )

            conn.commit()

        except sqlite3.IntegrityError:
            conn.close()
            return "Email already exists"

        conn.close()

        return redirect('/login')

    return render_template('register.html')


# Login
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM students WHERE email=?",
            (email,)
        )

        student = cursor.fetchone()

        conn.close()

        if student and check_password_hash(student['password'], password):

            session['student_id'] = student['id']
            session['name'] = student['name']

            return redirect('/dashboard')

        return "Invalid Email or Password"

    return render_template('login.html')


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

    return render_template(
        'chat.html',
        messages=messages,
        receiver_id=id
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


if __name__ == "__main__":
    app.run(debug=True)
