from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, date
import pandas as pd
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABASE MODEL ---
class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    day_name = db.Column(db.String(20))
    subject = db.Column(db.String(100))
    type = db.Column(db.String(20)) # "Theory" or "Lab"
    points = db.Column(db.Integer)
    status = db.Column(db.String(20), default="Pending") # Pending, Present, Absent

# --- EXCEL LOGIC ---
def process_excel(file, batch, start_str, end_str):
    # Clear old data
    db.session.query(Session).delete()
    db.session.commit()

    # Read Excel
    df = pd.read_excel(file, header=None)
    df.iloc[:, 0] = df.iloc[:, 0].ffill() # Fill merged day names

    schedule = {}
    
    # Parse Timetable
    for index, row in df.iterrows():
        if len(row) < 2: continue
        day_raw = str(row[0]).strip().upper()
        day_map = {
            "MON": "Monday", "MONDAY": "Monday", "TUE": "Tuesday", "TUESDAY": "Tuesday",
            "WED": "Wednesday", "WEDNESDAY": "Wednesday", "THU": "Thursday", "THURSDAY": "Thursday",
            "FRI": "Friday", "FRIDAY": "Friday", "SAT": "Saturday", "SATURDAY": "Saturday"
        }

        if day_raw in day_map:
            day = day_map[day_raw]
            if day not in schedule: schedule[day] = []
            
            for col in range(1, len(row)):
                cell = str(row[col]).strip()
                if cell not in ["nan", "-", "", "None"]:
                    is_lab = "LAB" in cell.upper() or batch.upper() in cell.upper()
                    points = 4 if is_lab else 2
                    type_ = "Lab" if is_lab else "Theory"
                    schedule[day].append({"name": cell, "type": type_, "points": points})

    # Timeline Generation
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()
    curr = start

    while curr <= end:
        day_name = curr.strftime("%A")
        if day_name in schedule:
            for cls in schedule[day_name]:
                new_session = Session(
                    date=curr,
                    day_name=day_name,
                    subject=cls['name'],
                    type=cls['type'],
                    points=cls['points'],
                    status="Pending"
                )
                db.session.add(new_session)
        curr += timedelta(days=1)
    
    db.session.commit()

# --- ROUTES ---
@app.route('/')
def dashboard():
    # Check if setup is needed
    if not Session.query.first():
        return redirect(url_for('setup'))
        
    today = date.today()
    sessions = Session.query.filter_by(date=today).all()
    
    # Quick Stats for Dashboard
    total_p = db.session.query(db.func.sum(Session.points)).filter(Session.status=='Present', Session.subject!='ELH').scalar() or 0
    total_a = db.session.query(db.func.sum(Session.points)).filter(Session.status=='Absent', Session.subject!='ELH').scalar() or 0
    conducted = total_p + total_a
    percentage = (total_p / conducted * 100) if conducted > 0 else 0
    
    return render_template('dashboard.html', sessions=sessions, today=today, pct=percentage)

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        f = request.files['file']
        batch = request.form['batch']
        start = request.form['start_date']
        end = request.form['end_date']
        
        if f:
            try:
                process_excel(f, batch, start, end)
                flash("Timetable Imported Successfully!", "success")
                return redirect(url_for('dashboard'))
            except Exception as e:
                flash(f"Error: {str(e)}", "danger")
                
    return render_template('setup.html')

@app.route('/mark/<int:id>/<status>')
def mark(id, status):
    s = Session.query.get(id)
    s.status = status
    db.session.commit()
    return redirect(request.referrer) # Go back to wherever we came from

@app.route('/history')
def history():
    # Group by date
    all_sessions = Session.query.order_by(Session.date.desc()).all()
    history_data = {}
    for s in all_sessions:
        d_str = s.date.strftime("%Y-%m-%d")
        if d_str not in history_data: history_data[d_str] = []
        history_data[d_str].append(s)
    return render_template('history.html', history=history_data)

@app.route('/stats')
def stats():
    # Complex query for subject-wise stats
    subjects = db.session.query(Session.subject).distinct().all()
    stats_data = []
    
    for sub in subjects:
        name = sub[0]
        if name == "ELH": continue
        
        earned = db.session.query(db.func.sum(Session.points)).filter_by(subject=name, status='Present').scalar() or 0
        lost = db.session.query(db.func.sum(Session.points)).filter_by(subject=name, status='Absent').scalar() or 0
        total = earned + lost
        pct = (earned/total*100) if total > 0 else 0
        
        stats_data.append({'name': name, 'pct': pct, 'total': total, 'earned': earned})
        
    return render_template('stats.html', stats=stats_data)

@app.route('/reset')
def reset():
    db.session.query(Session).delete()
    db.session.commit()
    return redirect(url_for('setup'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Create DB if not exists
    app.run(debug=True, port=5000)