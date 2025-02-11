from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_migrate import Migrate

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
# Configurazione del database in SQLite (l'utilizzo è locale)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///expenses.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Modelli del database
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    family = db.Column(db.String(100))
    preferences = db.Column(db.Text)
    expenses = db.relationship('Expense', backref='user', lazy=True)
    incomes = db.relationship('Income', backref='user', lazy=True)
    loans = db.relationship('Loan', backref='user', lazy=True)
    recurring_payments = db.relationship('RecurringPayment', backref='user', lazy=True)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10))  # 'borrowed' oppure 'lent'
    name = db.Column(db.String(100))
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class RecurringPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    recurrence = db.Column(db.String(50))  # es: "Giornaliero", "Settimanale", "Mensile", "Annuale"
    description = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

# Funzione per ottenere le notifiche di scadenza (entro 7 giorni)
def get_due_notifications():
    notifications = []
    today = datetime.now().date()
    threshold = today + timedelta(days=7)
    # Prestiti in scadenza
    upcoming_loans = Loan.query.filter(Loan.due_date <= threshold).all()
    for loan in upcoming_loans:
        notifications.append(f"Attenzione: {loan.name} ha scadenza il {loan.due_date.strftime('%d-%m-%Y')}")
    # Pagamenti ricorrenti in scadenza
    upcoming_recurring = RecurringPayment.query.filter(RecurringPayment.due_date <= threshold).all()
    for payment in upcoming_recurring:
        notifications.append(f"Attenzione: {payment.name} scade il {payment.due_date.strftime('%d-%m-%Y')}")
    return notifications

# Aggiungiamo il decorator per proteggere le route
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Devi essere loggato per accedere a questa pagina.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    notifications = get_due_notifications()
    return render_template('index.html', notifications=notifications)

@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    if request.method == 'POST':
        date_str = request.form.get('date')
        if date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            date = datetime.utcnow().date()
        new_expense = Expense(
            date=date,
            amount=float(request.form['amount']),
            category=request.form['category'],
            description=request.form.get('description'),
            user_id=session['user_id']
        )
        db.session.add(new_expense)
        db.session.commit()
        flash("Spesa aggiunta con successo!", "success")
        return redirect(url_for('expenses'))
    expenses_list = Expense.query.filter_by(user_id=session['user_id']).order_by(Expense.date.desc()).all()
    return render_template('expenses.html', expenses=expenses_list)

@app.route('/incomes', methods=['GET', 'POST'])
@login_required
def incomes():
    if request.method == 'POST':
        date_str = request.form.get('date')
        if date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            date = datetime.utcnow().date()
        new_income = Income(
            date=date,
            amount=float(request.form['amount']),
            category=request.form['category'],
            description=request.form.get('description'),
            user_id=session['user_id']
        )
        db.session.add(new_income)
        db.session.commit()
        flash("Entrata aggiunta con successo!", "success")
        return redirect(url_for('incomes'))
    incomes_list = Income.query.filter_by(user_id=session['user_id']).order_by(Income.date.desc()).all()
    return render_template('incomes.html', incomes=incomes_list)

@app.route('/balance', methods=['GET', 'POST'])
@login_required
def balance():
    if request.method == 'POST':
        year = int(request.form.get('year'))
        month = int(request.form.get('month'))
    else:
        year = request.args.get('year')
        month = request.args.get('month')
        if year and month:
            year = int(year)
            month = int(month)
        else:
            now = datetime.now()
            year = now.year
            month = now.month
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date()
    else:
        end_date = datetime(year, month + 1, 1).date()
    
    expenses_list = Expense.query.filter(
        Expense.date >= start_date, Expense.date < end_date,
        Expense.user_id == session['user_id']
    ).all()
    incomes_list = Income.query.filter(
        Income.date >= start_date, Income.date < end_date,
        Income.user_id == session['user_id']
    ).all()
    total_expenses = sum(exp.amount for exp in expenses_list)
    total_incomes = sum(inc.amount for inc in incomes_list)
    balance_value = total_incomes - total_expenses
    return render_template('balance.html', balance=balance_value, total_expenses=total_expenses, total_incomes=total_incomes, year=year, month=month)

@app.route('/charts')
def charts():
    # Accumula i dati delle categorie in spese e entrate per la rappresentazione grafica
    expenses_data = db.session.query(Expense.category, db.func.sum(Expense.amount)).group_by(Expense.category).all()
    incomes_data = db.session.query(Income.category, db.func.sum(Income.amount)).group_by(Income.category).all()
    expenses_categories = [cat for cat, _ in expenses_data]
    expenses_values = [val for _, val in expenses_data]
    incomes_categories = [cat for cat, _ in incomes_data]
    incomes_values = [val for _, val in incomes_data]
    return render_template('charts.html', 
                           expenses_categories=expenses_categories, 
                           expenses_values=expenses_values,
                           incomes_categories=incomes_categories,
                           incomes_values=incomes_values)

@app.route('/loans', methods=['GET', 'POST'])
@login_required
def loans():
    if request.method == 'POST':
        due_date_str = request.form.get('due_date')
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else datetime.utcnow().date()
        new_loan = Loan(
            type=request.form.get('type'),
            name=request.form.get('name'),
            amount=float(request.form['amount']),
            due_date=due_date,
            description=request.form.get('description'),
            user_id=session['user_id']
        )
        db.session.add(new_loan)
        db.session.commit()
        flash("Prestito registrato!", "success")
        return redirect(url_for('loans'))
    loans_list = Loan.query.filter_by(user_id=session['user_id']).order_by(Loan.due_date.desc()).all()
    return render_template('loans.html', loans=loans_list)

@app.route('/recurring', methods=['GET', 'POST'])
@login_required
def recurring():
    if request.method == 'POST':
        due_date_str = request.form.get('due_date')
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else datetime.utcnow().date()
        new_payment = RecurringPayment(
            name=request.form.get('name'),
            amount=float(request.form['amount']),
            due_date=due_date,
            recurrence=request.form.get('recurrence'),
            description=request.form.get('description'),
            user_id=session['user_id']
        )
        db.session.add(new_payment)
        db.session.commit()
        flash("Pagamento ricorrente registrato!", "success")
        return redirect(url_for('recurring'))
    payments_list = RecurringPayment.query.filter_by(user_id=session['user_id']).order_by(RecurringPayment.due_date.desc()).all()
    return render_template('recurring.html', payments=payments_list)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        family = request.form.get('family')
        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            flash("Username o Email già esistente.", "danger")
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password, family=family)
        db.session.add(new_user)
        db.session.commit()
        flash("Registrazione avvenuta con successo! Ora puoi fare il login.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password, password):
            flash("Credenziali non valide.", "danger")
            return redirect(url_for('login'))
        session['user_id'] = user.id
        flash("Login effettuato con successo.", "success")
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.pop('user_id', None)
    flash("Logout effettuato.", "success")
    return redirect(url_for('login'))

@app.route('/family')
@login_required
def family():
    current_user = User.query.get(session['user_id'])
    if not current_user.family:
        flash("Non fai parte di una famiglia.", "warning")
        return redirect(url_for('index'))
    family_members = User.query.filter_by(family=current_user.family).all()
    data = []
    for member in family_members:
        total_expenses = sum(exp.amount for exp in Expense.query.filter_by(user_id=member.id).all())
        total_incomes = sum(inc.amount for inc in Income.query.filter_by(user_id=member.id).all())
        data.append({"username": member.username, "total_expenses": total_expenses, "total_incomes": total_incomes})
    return render_template('family.html', data=data)

@app.route('/account')
@login_required
def account():
    user = User.query.get(session['user_id'])
    return render_template('account.html', user=user)

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('expenses.db'):
            db.create_all()
    app.run(debug=True) 