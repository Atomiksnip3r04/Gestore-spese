from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_migrate import Migrate
import plaid
from plaid.api import plaid_api

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
# Configurazione del database in SQLite (l'utilizzo è locale)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///expenses.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Configurazione del client Plaid in modalità Produzione
configuration = plaid.Configuration(
    host=plaid.Environment.Production,
    api_key={
         'clientId': os.environ.get('PLAID_PROD_CLIENT_ID', 'YOUR_PRODUCTION_CLIENT_ID'),
         'secret': os.environ.get('PLAID_PROD_SECRET', 'YOUR_PRODUCTION_SECRET'),
    }
)

api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)

# Modelli del database
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    family = db.Column(db.String(100))
    preferences = db.Column(db.Text)
    expenses = db.relationship('Expense', backref='user', cascade="all, delete-orphan", lazy=True)
    incomes = db.relationship('Income', backref='user', cascade="all, delete-orphan", lazy=True)
    loans = db.relationship('Loan', backref='user', cascade="all, delete-orphan", lazy=True)
    recurring_payments = db.relationship('RecurringPayment', backref='user', cascade="all, delete-orphan", lazy=True)
    notifications_enabled = db.Column(db.Boolean, default=True)
    family_expense_threshold = db.Column(db.Float, default=100.0)  # Soglia in € per notifiche push relative alle spese familiari
    avatar = db.Column(db.String(200), default='avatar1.jpg')  # Salva il nome del file avatar (presente in static/avatars)
    cards = db.relationship('Card', backref='user', cascade="all, delete-orphan", lazy=True)

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

# Nuovo modello per la registrazione delle carte di pagamento
class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_name = db.Column(db.String(100), nullable=False)
    card_network = db.Column(db.String(50))  # es. Visa, Mastercard
    masked_number = db.Column(db.String(20))  # es. "**** **** **** 1234"
    plaid_access_token = db.Column(db.String(500))
    transactions = db.relationship('Transaction', backref='card', cascade="all, delete-orphan", lazy=True)

# Nuovo modello per le transazioni
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(100), unique=True)  # memorizza l'ID della transazione fornito da Plaid
    date = db.Column(db.Date, default=datetime.utcnow, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'in' per entrate, 'out' per uscite
    description = db.Column(db.String(200))
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)

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
@login_required
def charts():
    user_id = session.get('user_id')
    # Accumula i dati delle categorie in spese e entrate per l'utente corrente
    expenses_data = db.session.query(Expense.category, db.func.sum(Expense.amount))\
                        .filter(Expense.user_id == user_id)\
                        .group_by(Expense.category).all()
    incomes_data = db.session.query(Income.category, db.func.sum(Income.amount))\
                        .filter(Income.user_id == user_id)\
                        .group_by(Income.category).all()
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

@app.route('/edit_expense/<int:expense_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if expense.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('expenses'))
    if request.method == 'POST':
        date_str = request.form.get('date')
        if date_str:
            expense.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        expense.amount = float(request.form.get('amount'))
        expense.category = request.form.get('category')
        expense.description = request.form.get('description')
        db.session.commit()
        flash("Spesa aggiornata", "success")
        return redirect(url_for('expenses'))
    return render_template('edit_expense.html', expense=expense)

@app.route('/delete_expense/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if expense.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('expenses'))
    db.session.delete(expense)
    db.session.commit()
    flash("Spesa eliminata", "success")
    return redirect(url_for('expenses'))

@app.route('/edit_income/<int:income_id>', methods=['GET', 'POST'])
@login_required
def edit_income(income_id):
    income = Income.query.get_or_404(income_id)
    if income.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('incomes'))
    if request.method == 'POST':
        date_str = request.form.get('date')
        if date_str:
            income.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        income.amount = float(request.form.get('amount'))
        income.category = request.form.get('category')
        income.description = request.form.get('description')
        db.session.commit()
        flash("Entrata aggiornata", "success")
        return redirect(url_for('incomes'))
    return render_template('edit_income.html', income=income)

@app.route('/delete_income/<int:income_id>', methods=['POST'])
@login_required
def delete_income(income_id):
    income = Income.query.get_or_404(income_id)
    if income.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('incomes'))
    db.session.delete(income)
    db.session.commit()
    flash("Entrata eliminata", "success")
    return redirect(url_for('incomes'))

@app.route('/edit_loan/<int:loan_id>', methods=['GET', 'POST'])
@login_required
def edit_loan(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    if loan.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('loans'))
    if request.method == 'POST':
        due_date_str = request.form.get('due_date')
        if due_date_str:
            loan.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        loan.type = request.form.get('type')
        loan.name = request.form.get('name')
        loan.amount = float(request.form.get('amount'))
        loan.description = request.form.get('description')
        db.session.commit()
        flash("Prestito aggiornato", "success")
        return redirect(url_for('loans'))
    return render_template('edit_loan.html', loan=loan)

@app.route('/delete_loan/<int:loan_id>', methods=['POST'])
@login_required
def delete_loan(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    if loan.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('loans'))
    db.session.delete(loan)
    db.session.commit()
    flash("Prestito eliminato", "success")
    return redirect(url_for('loans'))

@app.route('/edit_recurring/<int:recurring_id>', methods=['GET', 'POST'])
@login_required
def edit_recurring(recurring_id):
    recurring = RecurringPayment.query.get_or_404(recurring_id)
    if recurring.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('recurring'))
    if request.method == 'POST':
        due_date_str = request.form.get('due_date')
        if due_date_str:
            recurring.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        recurring.name = request.form.get('name')
        recurring.amount = float(request.form.get('amount'))
        recurring.recurrence = request.form.get('recurrence')
        recurring.description = request.form.get('description')
        db.session.commit()
        flash("Pagamento ricorrente aggiornato", "success")
        return redirect(url_for('recurring'))
    return render_template('edit_recurring.html', recurring=recurring)

@app.route('/delete_recurring/<int:recurring_id>', methods=['POST'])
@login_required
def delete_recurring(recurring_id):
    recurring = RecurringPayment.query.get_or_404(recurring_id)
    if recurring.user_id != session['user_id']:
        flash("Operazione non autorizzata", "danger")
        return redirect(url_for('recurring'))
    db.session.delete(recurring)
    db.session.commit()
    flash("Pagamento ricorrente eliminato", "success")
    return redirect(url_for('recurring'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash("Password aggiornata", "success")
        return redirect(url_for('account'))
    return render_template('change_password.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        family = request.form.get('family')
        avatar = request.form.get('avatar', 'avatar1.png')
        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            flash("Username o Email già esistente.", "danger")
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password, family=family, avatar=avatar)
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
    # Tutti gli utenti registrati appartengono alla famiglia "Ciconte"
    family_members = User.query.filter_by(family="Ciconte").all()
    data = []
    for member in family_members:
         total_expenses = sum(exp.amount for exp in Expense.query.filter_by(user_id=member.id).all())
         recent_expense = Expense.query.filter_by(user_id=member.id).order_by(Expense.date.desc()).first()
         largest_expense = Expense.query.filter_by(user_id=member.id).order_by(Expense.amount.desc()).first()
         data.append({
              "member": member,
              "total_expenses": total_expenses,
              "recent_expense": recent_expense,
              "largest_expense": largest_expense
         })
    return render_template('family.html', family_data=data)

@app.route('/family/detail/<int:member_id>')
@login_required
def family_detail(member_id):
    member = User.query.get_or_404(member_id)
    expenses_list = Expense.query.filter_by(user_id=member.id).order_by(Expense.date.desc()).all()
    incomes_list = Income.query.filter_by(user_id=member.id).order_by(Income.date.desc()).all()
    loans_list = Loan.query.filter_by(user_id=member.id).order_by(Loan.due_date.desc()).all()
    recurring_list = RecurringPayment.query.filter_by(user_id=member.id).order_by(RecurringPayment.due_date.desc()).all()
    return render_template('family_detail.html', member=member, expenses=expenses_list, incomes=incomes_list, loans=loans_list, recurring=recurring_list)

@app.route('/account')
@login_required
def account():
    user = User.query.get(session['user_id'])
    return render_template('account.html', user=user)

@app.route('/update_notifications', methods=['POST'])
@login_required
def update_notifications():
    user = User.query.get(session['user_id'])
    notifications_enabled = request.form.get('notifications_enabled') == 'on'
    user.notifications_enabled = notifications_enabled
    # Aggiorna anche la soglia per le notifiche delle spese familiari
    try:
         threshold = float(request.form.get('family_expense_threshold', user.family_expense_threshold))
         user.family_expense_threshold = threshold
    except (ValueError, TypeError):
         pass
    db.session.commit()
    flash("Preferenze notifiche aggiornate.", "success")
    return redirect(url_for('account'))

@app.route('/api/reminders')
@login_required
def api_reminders():
    user = User.query.get(session['user_id'])
    if not user.notifications_enabled:
        return jsonify([])
    reminders = []
    # Imposta un threshold: notificare eventi che scadono entro le prossime 24 ore.
    threshold = datetime.now().date() + timedelta(days=1)
    upcoming_loans = Loan.query.filter(Loan.due_date <= threshold, Loan.user_id == user.id).all()
    for loan in upcoming_loans:
        reminders.append(f"Prestito '{loan.name}' scade il {loan.due_date.strftime('%d-%m-%Y')}")
    upcoming_recurring = RecurringPayment.query.filter(RecurringPayment.due_date <= threshold, RecurringPayment.user_id == user.id).all()
    for rp in upcoming_recurring:
        reminders.append(f"Pagamento ricorrente '{rp.name}' scade il {rp.due_date.strftime('%d-%m-%Y')}")
    return jsonify(reminders)

@app.route('/transactions', methods=['GET', 'POST'])
@login_required
def transactions():
    # Otteniamo l'elenco delle carte registrate per l'utente (per il dropdown)
    cards = Card.query.filter_by(user_id=session['user_id']).all()
    selected_card = request.args.get('card_id', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Se non sono specificate date, usiamo il mese corrente come default
    if not start_date or not end_date:
        now = datetime.now()
        start_date = datetime(now.year, now.month, 1).date()
        if now.month == 12:
            end_date = datetime(now.year + 1, 1, 1).date()
        else:
            end_date = datetime(now.year, now.month + 1, 1).date()
    else:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

    # Filtriamo le transazioni: solo quelle del corrente utente e nel periodo
    query = Transaction.query.join(Card).filter(Card.user_id == session['user_id'])
    query = query.filter(Transaction.date >= start_date, Transaction.date < end_date)

    if selected_card != 'all':
        query = query.filter(Transaction.card_id == int(selected_card))

    transactions_list = query.order_by(Transaction.date.desc()).all()

    # Calcoliamo il totale delle entrate e uscite per il periodo selezionato
    total_in = sum(t.amount for t in transactions_list if t.direction == 'in')
    total_out = sum(t.amount for t in transactions_list if t.direction == 'out')

    return render_template('transactions.html', 
                           transactions=transactions_list, 
                           cards=cards, 
                           selected_card=selected_card, 
                           start_date=start_date, 
                           end_date=end_date, 
                           total_in=total_in, 
                           total_out=total_out)

@app.route('/add_transaction', methods=['GET', 'POST'])
@login_required
def add_transaction():
    cards = Card.query.filter_by(user_id=session['user_id']).all()
    if request.method == 'POST':
        date_str = request.form.get('date')
        if date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            date = datetime.utcnow().date()
        amount = float(request.form.get('amount'))
        direction = request.form.get('direction')  # 'in' o 'out'
        description = request.form.get('description')
        card_id = int(request.form.get('card_id'))
        new_transaction = Transaction(date=date, amount=amount, direction=direction, description=description, card_id=card_id)
        db.session.add(new_transaction)
        db.session.commit()
        flash("Transazione aggiunta", "success")
        return redirect(url_for('transactions'))
    return render_template('add_transaction.html', cards=cards)

@app.route('/cards', methods=['GET', 'POST'])
@login_required
def cards():
    if request.method == 'POST':
        card_name = request.form.get('card_name')
        card_network = request.form.get('card_network')
        masked_number = request.form.get('masked_number')
        new_card = Card(user_id=session['user_id'], card_name=card_name, card_network=card_network, masked_number=masked_number)
        db.session.add(new_card)
        db.session.commit()
        flash("Carta aggiunta", "success")
        return redirect(url_for('cards'))
    cards = Card.query.filter_by(user_id=session['user_id']).all()
    return render_template('cards.html', cards=cards)

@app.route('/create_link_token', methods=['POST'])
def create_link_token():
    # Assicurati di avere un ID utente (ad esempio, nella sessione)
    user_id = session.get('user_id', 'default_user')
    request_payload = {
         "user": {"client_user_id": str(user_id)},
         "client_name": "Il Mio App",
         "products": ["transactions"],
         "country_codes": ["US", "IT"],  # Aggiungi i paesi appropriati
         "language": "it",
         "redirect_uri": "http://localhost:5000/plaid_redirect"  # URI di reindirizzamento
    }
    response = plaid_client.link_token_create(request_payload)
    link_token = response.to_dict()['link_token']
    return jsonify({"link_token": link_token})

@app.route('/exchange_public_token', methods=['POST'])
def exchange_public_token():
    # Ricevi il public token dal frontend
    public_token = request.json.get("public_token")
    exchange_request = {"public_token": public_token}
    response = plaid_client.item_public_token_exchange(exchange_request)
    access_token = response.to_dict()['access_token']

    # Salva l'access_token associandolo a una carta nel database.
    # Ad esempio, se l'utente ha già una carta (oppure creane una nuova):
    card = Card.query.filter_by(user_id=session['user_id'], card_name="Conto Bancario").first()
    if not card:
         card = Card(user_id=session['user_id'], card_name="Conto Bancario", plaid_access_token=access_token)
         db.session.add(card)
    else:
         card.plaid_access_token = access_token
    db.session.commit()

    return jsonify({"result": "success", "access_token": access_token})

@app.route('/plaid_redirect')
def plaid_redirect():
    return render_template('plaid_redirect.html')

@app.route('/collega_carta')
def collega_carta():
    return render_template('plaid_link.html')

@app.route('/sync_transactions', methods=['GET'])
@login_required
def sync_transactions():
    # Recupera le carte collegate dell'utente
    cards = Card.query.filter_by(user_id=session['user_id']).all()
    if not cards:
         flash("Nessun conto bancario collegato. Prima collega un conto!", "warning")
         return redirect(url_for('collega_carta'))

    for card in cards:
         if not card.plaid_access_token:
              continue

         # Imposta l'intervallo di sincronizzazione, ad esempio gli ultimi 30 giorni
         start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
         end_date = datetime.now().strftime('%Y-%m-%d')

         # Per ottenere le transazioni servono gli oggetti TransactionsGetRequest e Options
         from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
         from plaid.model.transactions_get_request import TransactionsGetRequest

         options = TransactionsGetRequestOptions(count=100, offset=0)
         request = TransactionsGetRequest(
                     access_token=card.plaid_access_token,
                     start_date=start_date,
                     end_date=end_date,
                     options=options
                  )
         response = plaid_client.transactions_get(request)
         transactions_data = response.to_dict().get('transactions', [])

         for t in transactions_data:
              # Controlla se la transazione è già stata registrata
              if not Transaction.query.filter_by(external_id=t['transaction_id']).first():
                  # Imposta una logica per il campo "direction" (questo è un esempio semplice)
                  direction = 'in' if t['amount'] < 0 else 'out'
                  new_transaction = Transaction(
                      external_id=t['transaction_id'],
                      date=datetime.strptime(t['date'], '%Y-%m-%d').date(),
                      amount=t['amount'],
                      direction=direction,
                      description=t['name'],
                      card_id=card.id
                  )
                  db.session.add(new_transaction)
         db.session.commit()

    flash("Transazioni sincronizzate correttamente!", "success")
    return redirect(url_for('transactions'))

@app.route('/api/family_expense_notifications')
@login_required
def api_family_expense_notifications():
    current_user = User.query.get(session['user_id'])
    if not current_user.notifications_enabled:
         return jsonify([])
    notifications = []
    # Considera tutti i membri della stessa famiglia
    family_members = User.query.filter_by(family=current_user.family).all()
    threshold = current_user.family_expense_threshold
    # Considera solo le spese registrate negli ultimi 1 giorno per evitare notifiche ripetute
    since = datetime.now() - timedelta(days=1)
    for member in family_members:
         high_expenses = Expense.query.filter(
             Expense.user_id == member.id,
             Expense.amount >= threshold,
             Expense.date >= since.date()
         ).all()
         for expense in high_expenses:
              notifications.append(
                 f"Attenzione: {member.username} ha registrato una spesa di {expense.amount}€ il {expense.date.strftime('%d-%m-%Y')} che supera la soglia di {threshold}€."
              )
    return jsonify(notifications)

@app.route('/update_password', methods=['POST'])
@login_required
def update_password():
    user = User.query.get(session['user_id'])
    new_password = request.form.get('new_password')
    if new_password:
        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash("Password aggiornata con successo.", "success")
    else:
        flash("Inserisci una nuova password.", "danger")
    return redirect(url_for('account'))

@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user = User.query.get(session['user_id'])
    db.session.delete(user)
    db.session.commit()
    session.pop('user_id', None)
    flash("Account eliminato con successo.", "success")
    return redirect(url_for('index'))

# Aggiungi un context processor per rendere disponibile current_user in ogni template
@app.context_processor
def inject_current_user():
    if 'user_id' in session:
         user = User.query.get(session['user_id'])
         return dict(current_user=user)
    return dict(current_user=None)

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('expenses.db'):
            db.create_all()
    # Esegue l'app in modalità development bindata a tutte le interfacce (0.0.0.0)
    # In questo modo, potrai accedere al sito su altri dispositivi usando l'indirizzo IP della macchina
    app.run(host='0.0.0.0', port=5000, debug=True) 