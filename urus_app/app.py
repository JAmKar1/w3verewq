# -*- coding: utf-8 -*-
"""URUS — Библиотечный учёт. Flask + SQLite."""
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, Response
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'urus-secret-key'

DB_PATH = 'urus.db'

LOAN_DAYS = 14


# ---------- База данных ----------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            is_blocked INTEGER DEFAULT 0,
            failed_attempts INTEGER DEFAULT 0,
            first_login INTEGER DEFAULT 1,
            last_login TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            genre TEXT NOT NULL,
            year INTEGER,
            status TEXT NOT NULL DEFAULT 'available',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS readers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id),
            reader_id INTEGER NOT NULL REFERENCES readers(id),
            employee TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            due_at TEXT NOT NULL,
            returned_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            book_title TEXT,
            reader_name TEXT,
            employee TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id),
            reader_id INTEGER NOT NULL REFERENCES readers(id),
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # Миграция: добавляем user_id в readers, если его нет
    cols = [row[1] for row in db.execute('PRAGMA table_info(readers)').fetchall()]
    if 'user_id' not in cols:
        db.execute('ALTER TABLE readers ADD COLUMN user_id INTEGER REFERENCES users(id)')

    loan_cols = [row[1] for row in db.execute('PRAGMA table_info(loans)').fetchall()]
    if 'renewals' not in loan_cols:
        db.execute('ALTER TABLE loans ADD COLUMN renewals INTEGER DEFAULT 0')

    if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        db.execute(
            'INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, ?)',
            ('admin', generate_password_hash('admin123'), 'admin', 0)
        )
        db.execute(
            'INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, ?)',
            ('ivanova', generate_password_hash('12345'), 'user', 1)
        )
        db.execute(
            'INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, ?)',
            ('petrov', generate_password_hash('12345'), 'user', 0)
        )
        db.execute(
            'INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, ?)',
            ('reader1', generate_password_hash('12345'), 'reader', 0)
        )
    else:
        # Миграция тестового читателя для существующей базы
        has_reader = db.execute(
            'SELECT id FROM users WHERE login = ?', ('reader1',)
        ).fetchone()
        if has_reader is None:
            db.execute(
                'INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, ?)',
                ('reader1', generate_password_hash('12345'), 'reader', 0)
            )
            db.commit()

    if db.execute('SELECT COUNT(*) FROM books').fetchone()[0] == 0:
        books = [
            ('Война и мир', 'Лев Толстой', 'Роман', 1869),
            ('Преступление и наказание', 'Фёдор Достоевский', 'Роман', 1866),
            ('Мастер и Маргарита', 'Михаил Булгаков', 'Роман', 1967),
            ('Евгений Онегин', 'Александр Пушкин', 'Поэзия', 1833),
            ('Тихий Дон', 'Михаил Шолохов', 'Роман', 1940),
            ('Два капитана', 'Вениамин Каверин', 'Приключения', 1938),
            ('Собачье сердце', 'Михаил Булгаков', 'Повесть', 1925),
            ('Отцы и дети', 'Иван Тургенев', 'Роман', 1862),
        ]
        db.executemany(
            'INSERT INTO books (title, author, genre, year) VALUES (?, ?, ?, ?)',
            books
        )

    if db.execute('SELECT COUNT(*) FROM readers').fetchone()[0] == 0:
        reader_user = db.execute(
            "SELECT id FROM users WHERE login = 'reader1'"
        ).fetchone()
        reader_user_id = reader_user['id'] if reader_user else None
        readers = [
            ('Иванова Анна Сергеевна', '+7 (912) 345-67-89', None),
            ('Петров Дмитрий Иванович', '+7 (923) 456-78-90', None),
            ('Сидорова Мария Петровна', '+7 (934) 567-89-01', reader_user_id),
        ]
        db.executemany(
            'INSERT INTO readers (full_name, phone, user_id) VALUES (?, ?, ?)',
            readers
        )

    db.commit()
    db.close()


def log_operation(operation, book_title=None, reader_name=None, employee=None):
    db = get_db()
    db.execute(
        'INSERT INTO journal (operation, book_title, reader_name, employee) VALUES (?, ?, ?, ?)',
        (operation, book_title, reader_name, employee)
    )
    db.commit()


# ---------- Вспомогательные функции ----------

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Доступ запрещён: раздел доступен только администратору', 'error')
            return redirect(url_for('dashboard'))
        return view(*args, **kwargs)
    return wrapper


def staff_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') not in ('user', 'admin'):
            flash('Доступ запрещён: раздел доступен только сотрудникам библиотеки', 'error')
            return redirect(url_for('reader_dashboard'))
        return view(*args, **kwargs)
    return wrapper


def reader_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'reader':
            flash('Доступ запрещён: раздел доступен только читателю', 'error')
            return redirect(url_for('dashboard'))
        return view(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    from flask import get_flashed_messages
    return {'current_user_login': session.get('login', ''),
            'current_user_role': session.get('role', ''),
            'requests_badge': _requests_badge()}


def _requests_badge():
    if session.get('role') not in ('user', 'admin'):
        return 0
    db = get_db()
    return db.execute(
        "SELECT COUNT(*) FROM reservations WHERE status = 'new'"
    ).fetchone()[0]


# ---------- Авторизация ----------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_name = request.form.get('login', '').strip()
        password = request.form.get('password', '')

        if not login_name or not password:
            flash('Заполните все обязательные поля', 'error')
            return render_template('login.html')

        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE login = ?', (login_name,)
        ).fetchone()

        if user is None:
            flash('Вы ввели неверный логин или пароль. '
                  'Пожалуйста проверьте ещё раз введенные данные', 'error')
            return render_template('login.html')

        if user['is_blocked']:
            flash('Вы заблокированы. Обратитесь к администратору', 'error')
            return render_template('login.html')

        # Проверка капчи-пазла
        if 'captcha_fails' not in session:
            session['captcha_fails'] = 0

        captcha_solved = request.form.get('captcha_solved', 'false')
        if captcha_solved != 'true':
            session['captcha_fails'] += 1
            if session['captcha_fails'] >= 3:
                db.execute(
                    'UPDATE users SET is_blocked = 1 WHERE id = ?', (user['id'],)
                )
                db.commit()
                flash('Вы заблокированы. Обратитесь к администратору', 'error')
            else:
                flash('Капча не собрана. Осталось попыток: %d'
                      % (3 - session['captcha_fails']), 'error')
            return render_template('login.html')

        session['captcha_fails'] = 0

        # Блокировка, если не входил более 1 месяца
        if user['last_login']:
            try:
                last = datetime.strptime(user['last_login'], '%Y-%m-%d %H:%M:%S')
                if datetime.now() - last > timedelta(days=30):
                    db.execute('UPDATE users SET is_blocked = 1 WHERE id = ?', (user['id'],))
                    db.commit()
                    flash('Вы заблокированы. Обратитесь к администратору', 'error')
                    return render_template('login.html')
            except ValueError:
                pass

        if not check_password_hash(user['password_hash'], password):
            attempts = user['failed_attempts'] + 1
            if attempts >= 3:
                db.execute(
                    'UPDATE users SET is_blocked = 1, failed_attempts = ? WHERE id = ?',
                    (attempts, user['id'])
                )
                db.commit()
                session['captcha_fails'] = 0
                flash('Вы заблокированы. Обратитесь к администратору', 'error')
            else:
                db.execute(
                    'UPDATE users SET failed_attempts = ? WHERE id = ?',
                    (attempts, user['id'])
                )
                db.commit()
                flash('Вы ввели неверный логин или пароль. '
                      'Пожалуйста проверьте ещё раз введенные данные', 'error')
            return render_template('login.html')

        db.execute(
            'UPDATE users SET failed_attempts = 0, last_login = ? WHERE id = ?',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user['id'])
        )
        db.commit()
        session.pop('captcha_fails', None)

        session['user_id'] = user['id']
        session['login'] = user['login']
        session['role'] = user['role']
        flash('Вы успешно авторизовались', 'success')

        if user['first_login']:
            return redirect(url_for('change_password'))
        if user['role'] == 'reader':
            return redirect(url_for('reader_dashboard'))
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        login_name = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not full_name or not phone or not login_name or not password or not confirm:
            flash('Заполните все обязательные поля', 'error')
            return render_template('register.html')

        if password != confirm:
            flash('Пароль и подтверждение не совпадают', 'error')
            return render_template('register.html')

        if len(password) < 5:
            flash('Пароль должен содержать не менее 5 символов', 'error')
            return render_template('register.html')

        db = get_db()
        exists = db.execute('SELECT id FROM users WHERE login = ?', (login_name,)).fetchone()
        if exists:
            flash('Пользователь с логином «%s» уже существует' % login_name, 'error')
            return render_template('register.html')

        db.execute(
            "INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, 'reader', 0)",
            (login_name, generate_password_hash(password))
        )
        user = db.execute('SELECT id FROM users WHERE login = ?', (login_name,)).fetchone()
        db.execute(
            'INSERT INTO readers (full_name, phone, user_id) VALUES (?, ?, ?)',
            (full_name, phone, user['id'])
        )
        log_operation('Регистрация читателя', None, full_name, login_name)
        db.commit()

        session['user_id'] = user['id']
        session['login'] = login_name
        session['role'] = 'reader'
        flash('Регистрация завершена. Добро пожаловать в библиотеку', 'success')
        return redirect(url_for('reader_dashboard'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('login'))


# ---------- Смена пароля ----------

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        if not current or not new or not confirm:
            flash('Заполните все обязательные поля', 'error')
            return render_template('change_password.html')

        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE id = ?', (session['user_id'],)
        ).fetchone()

        if not check_password_hash(user['password_hash'], current):
            flash('Текущий пароль введён неверно', 'error')
            return render_template('change_password.html')

        if new != confirm:
            flash('Новый пароль и подтверждение не совпадают', 'error')
            return render_template('change_password.html')

        db.execute(
            'UPDATE users SET password_hash = ?, first_login = 0 WHERE id = ?',
            (generate_password_hash(new), user['id'])
        )
        db.commit()
        flash('Пароль успешно изменён', 'success')
        return redirect(url_for('dashboard'))

    return render_template('change_password.html')


# ---------- Личный кабинет читателя ----------

@app.route('/reader')
@reader_required
def reader_dashboard():
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    reader = db.execute(
        'SELECT * FROM readers WHERE user_id = ?', (session['user_id'],)
    ).fetchone()

    loans = []
    reservations = []
    if reader is not None:
        loans = db.execute('''
            SELECT b.title, b.author, l.issued_at, l.due_at, l.returned_at,
                   l.renewals, l.id AS loan_id
            FROM loans l
            JOIN books b ON b.id = l.book_id
            WHERE l.reader_id = ?
            ORDER BY l.issued_at DESC
        ''', (reader['id'],)).fetchall()

        reservations = db.execute('''
            SELECT r.id, b.title, b.author, r.status, r.created_at
            FROM reservations r
            JOIN books b ON b.id = r.book_id
            WHERE r.reader_id = ?
            ORDER BY r.created_at DESC
        ''', (reader['id'],)).fetchall()

    return render_template(
        'reader_dashboard.html',
        reader=reader,
        loans=loans,
        reservations=reservations,
        today=today,
        page='reader'
    )


@app.route('/reader/reserve/<int:book_id>', methods=['POST'])
@reader_required
def reserve_book(book_id):
    db = get_db()
    reader = db.execute(
        'SELECT * FROM readers WHERE user_id = ?', (session['user_id'],)
    ).fetchone()
    if reader is None:
        flash('Профиль читателя не найден. Обратитесь к сотруднику библиотеки', 'error')
        return redirect(url_for('catalog'))

    book = db.execute('SELECT * FROM books WHERE id = ?', (book_id,)).fetchone()
    if book is None:
        flash('Книга не найдена', 'error')
        return redirect(url_for('catalog'))

    issued = db.execute(
        'SELECT id FROM loans WHERE book_id = ? AND returned_at IS NULL', (book_id,)
    ).fetchone()
    if issued:
        flash('Книга «%s» сейчас на руках, бронирование недоступно' % book['title'], 'error')
        return redirect(url_for('catalog'))

    own = db.execute(
        "SELECT id FROM reservations WHERE book_id = ? AND reader_id = ? AND status = 'new'",
        (book_id, reader['id'])
    ).fetchone()
    if own:
        flash('Вы уже оставили заявку на книгу «%s»' % book['title'], 'error')
        return redirect(url_for('catalog'))

    hold = db.execute(
        "SELECT id FROM reservations WHERE book_id = ? AND status IN ('new', 'approved')",
        (book_id,)
    ).fetchone()
    if hold:
        flash('Книга «%s» уже забронирована другим читателем' % book['title'], 'error')
        return redirect(url_for('catalog'))

    db.execute(
        'INSERT INTO reservations (book_id, reader_id) VALUES (?, ?)',
        (book_id, reader['id'])
    )
    log_operation('Заявка', book['title'], reader['full_name'], session['login'])
    db.commit()
    flash('Заявка на книгу «%s» отправлена. Ожидайте подтверждения сотрудника' % book['title'], 'success')
    return redirect(url_for('reader_dashboard'))


@app.route('/reader/reservation/<int:res_id>/cancel', methods=['POST'])
@reader_required
def cancel_reservation(res_id):
    db = get_db()
    reader = db.execute(
        'SELECT * FROM readers WHERE user_id = ?', (session['user_id'],)
    ).fetchone()
    if reader is None:
        return redirect(url_for('catalog'))

    res = db.execute(
        "SELECT * FROM reservations WHERE id = ? AND reader_id = ? AND status = 'new'",
        (res_id, reader['id'])
    ).fetchone()
    if res is None:
        flash('Заявка не найдена или уже обработана', 'error')
        return redirect(url_for('reader_dashboard'))

    db.execute('UPDATE reservations SET status = ? WHERE id = ?', ('declined', res_id))
    book = db.execute('SELECT title FROM books WHERE id = ?', (res['book_id'],)).fetchone()
    log_operation('Отмена заявки', book['title'] if book else None,
                  reader['full_name'], session['login'])
    db.commit()
    flash('Заявка отменена', 'success')
    return redirect(url_for('reader_dashboard'))


@app.route('/reader/loan/<int:loan_id>/renew', methods=['POST'])
@reader_required
def renew_loan(loan_id):
    db = get_db()
    reader = db.execute(
        'SELECT * FROM readers WHERE user_id = ?', (session['user_id'],)
    ).fetchone()
    if reader is None:
        return redirect(url_for('catalog'))

    loan = db.execute('''
        SELECT l.*, b.title FROM loans l
        JOIN books b ON b.id = l.book_id
        WHERE l.id = ? AND l.reader_id = ?
    ''', (loan_id, reader['id'])).fetchone()

    if loan is None or loan['returned_at'] is not None:
        flash('Выдача не найдена или книга уже возвращена', 'error')
        return redirect(url_for('reader_dashboard'))

    if loan['renewals'] >= 1:
        flash('Эта выдача уже была продлена. Повторное продление недоступно', 'error')
        return redirect(url_for('reader_dashboard'))

    today = datetime.now().strftime('%Y-%m-%d')
    if loan['due_at'] < today:
        flash('Просроченные книги не подлежат продлению. Верните книгу в библиотеку', 'error')
        return redirect(url_for('reader_dashboard'))

    new_due = (
        datetime.strptime(loan['due_at'], '%Y-%m-%d') + timedelta(days=LOAN_DAYS)
    ).strftime('%Y-%m-%d')
    db.execute(
        'UPDATE loans SET due_at = ?, renewals = renewals + 1 WHERE id = ?',
        (new_due, loan_id)
    )
    log_operation('Продление', loan['title'], reader['full_name'], session['login'])
    db.commit()
    flash('Срок возврата книги «%s» продлён до %s' % (loan['title'], new_due), 'success')
    return redirect(url_for('reader_dashboard'))


# ---------- Заявки читателей ----------

@app.route('/requests')
@staff_required
def requests_page():
    db = get_db()
    rows = db.execute('''
        SELECT r.id, b.title, b.author, r2.full_name, r2.phone, r.created_at
        FROM reservations r
        JOIN books b ON b.id = r.book_id
        JOIN readers r2 ON r2.id = r.reader_id
        WHERE r.status = 'new'
        ORDER BY r.created_at
    ''').fetchall()
    return render_template('requests.html', requests=rows, page='requests')


@app.route('/requests/<int:res_id>/approve', methods=['POST'])
@staff_required
def approve_request(res_id):
    db = get_db()
    res = db.execute(
        "SELECT * FROM reservations WHERE id = ? AND status = 'new'", (res_id,)
    ).fetchone()
    if res is None:
        flash('Заявка не найдена или уже обработана', 'error')
        return redirect(url_for('requests_page'))

    book = db.execute('SELECT * FROM books WHERE id = ?', (res['book_id'],)).fetchone()
    reader = db.execute('SELECT * FROM readers WHERE id = ?', (res['reader_id'],)).fetchone()

    issued = db.execute(
        'SELECT id FROM loans WHERE book_id = ? AND returned_at IS NULL', (res['book_id'],)
    ).fetchone()
    if issued or book is None or book['status'] != 'available':
        flash('Книга уже выдана, заявку нельзя выполнить', 'error')
        db.execute("UPDATE reservations SET status = 'declined' WHERE id = ?", (res_id,))
        db.commit()
        return redirect(url_for('requests_page'))

    now = datetime.now()
    db.execute(
        'INSERT INTO loans (book_id, reader_id, employee, issued_at, due_at) VALUES (?, ?, ?, ?, ?)',
        (res['book_id'], res['reader_id'], session['login'],
         now.strftime('%Y-%m-%d'),
         (now + timedelta(days=LOAN_DAYS)).strftime('%Y-%m-%d'))
    )
    db.execute('UPDATE books SET status = ? WHERE id = ?', ('issued', res['book_id']))
    db.execute("UPDATE reservations SET status = 'approved' WHERE id = ?", (res_id,))
    log_operation('Выдача по заявке', book['title'],
                  reader['full_name'] if reader else None, session['login'])
    db.commit()
    flash('Заявка выполнена: книга «%s» выдана' % book['title'], 'success')
    return redirect(url_for('requests_page'))


@app.route('/requests/<int:res_id>/decline', methods=['POST'])
@staff_required
def decline_request(res_id):
    db = get_db()
    res = db.execute(
        "SELECT * FROM reservations WHERE id = ? AND status = 'new'", (res_id,)
    ).fetchone()
    if res is None:
        flash('Заявка не найдена или уже обработана', 'error')
        return redirect(url_for('requests_page'))

    db.execute("UPDATE reservations SET status = 'declined' WHERE id = ?", (res_id,))
    log_operation('Отказ по заявке', None, None, session['login'])
    db.commit()
    flash('Заявка отклонена', 'success')
    return redirect(url_for('requests_page'))


# ---------- Рабочий стол ----------

@app.route('/')
@staff_required
def dashboard():
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    issued_today = db.execute(
        "SELECT COUNT(*) FROM loans WHERE issued_at LIKE ?", (today + '%',)
    ).fetchone()[0]

    returned_today = db.execute(
        "SELECT COUNT(*) FROM loans WHERE returned_at IS NOT NULL AND returned_at LIKE ?",
        (today + '%',)
    ).fetchone()[0]

    overdue_count = db.execute(
        "SELECT COUNT(*) FROM loans WHERE returned_at IS NULL AND due_at < ?",
        (today,)
    ).fetchone()[0]

    readers_total = db.execute('SELECT COUNT(*) FROM readers').fetchone()[0]

    journal = db.execute(
        "SELECT * FROM journal WHERE created_at LIKE ? ORDER BY created_at DESC",
        (today + '%',)
    ).fetchall()

    expiring = db.execute(
        "SELECT COUNT(*) FROM loans WHERE returned_at IS NULL AND due_at >= ? AND due_at <= ?",
        (today, (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d'))
    ).fetchone()[0]

    requests_count = db.execute(
        "SELECT COUNT(*) FROM reservations WHERE status = 'new'"
    ).fetchone()[0]

    return render_template(
        'dashboard.html',
        issued_today=issued_today,
        returned_today=returned_today,
        overdue_count=overdue_count,
        readers_total=readers_total,
        journal=journal,
        expiring=expiring,
        requests_count=requests_count,
        page='dashboard'
    )


# ---------- Каталог ----------

@app.route('/catalog')
@login_required
def catalog():
    db = get_db()
    search = request.args.get('search', '').strip()
    genre = request.args.get('genre', '')
    status = request.args.get('status', '')

    query = 'SELECT * FROM books WHERE 1=1'
    params = []
    if search:
        query += ' AND (title LIKE ? OR author LIKE ?)'
        params.extend(['%' + search + '%', '%' + search + '%'])
    if genre:
        query += ' AND genre = ?'
        params.append(genre)
    if status:
        query += ' AND status = ?'
        params.append(status)
    query += ' ORDER BY title'

    books = db.execute(query, params).fetchall()
    genres = db.execute('SELECT DISTINCT genre FROM books ORDER BY genre').fetchall()

    return render_template(
        'catalog.html', books=books, genres=genres,
        search=search, genre=genre, status=status, page='catalog'
    )


@app.route('/catalog/issue/<int:book_id>', methods=['POST'])
@staff_required
def issue_book(book_id):
    db = get_db()
    book = db.execute('SELECT * FROM books WHERE id = ?', (book_id,)).fetchone()
    if book is None or book['status'] != 'available':
        flash('Книга недоступна для выдачи', 'error')
        return redirect(url_for('catalog'))

    reader = db.execute('SELECT * FROM readers ORDER BY id LIMIT 1').fetchone()
    if reader is None:
        flash('Нет зарегистрированных читателей', 'error')
        return redirect(url_for('catalog'))

    now = datetime.now()
    db.execute(
        'INSERT INTO loans (book_id, reader_id, employee, issued_at, due_at) VALUES (?, ?, ?, ?, ?)',
        (book_id, reader['id'], session['login'],
         now.strftime('%Y-%m-%d'),
         (now + timedelta(days=LOAN_DAYS)).strftime('%Y-%m-%d'))
    )
    db.execute('UPDATE books SET status = ? WHERE id = ?', ('issued', book_id))
    log_operation('Выдача', book['title'], reader['full_name'], session['login'])
    db.commit()
    flash('Книга «%s» выдана' % book['title'], 'success')
    return redirect(url_for('catalog'))


@app.route('/catalog/add', methods=['POST'])
@staff_required
def add_book():
    title = request.form.get('title', '').strip()
    author = request.form.get('author', '').strip()
    genre = request.form.get('genre', '').strip()
    year_raw = request.form.get('year', '').strip()

    if not title or not author or not genre:
        flash('Заполните название, автора и жанр издания', 'error')
        return redirect(url_for('catalog'))

    year = None
    if year_raw:
        try:
            year = int(year_raw)
        except ValueError:
            flash('Год издания должен быть числом', 'error')
            return redirect(url_for('catalog'))

    db = get_db()
    db.execute(
        'INSERT INTO books (title, author, genre, year) VALUES (?, ?, ?, ?)',
        (title, author, genre, year)
    )
    log_operation('Добавление издания', title, None, session['login'])
    db.commit()
    flash('Издание «%s» добавлено в каталог' % title, 'success')
    return redirect(url_for('catalog'))


@app.route('/catalog/return/<int:book_id>', methods=['POST'])
@staff_required
def return_book(book_id):
    db = get_db()
    book = db.execute('SELECT * FROM books WHERE id = ?', (book_id,)).fetchone()
    if book is None or book['status'] != 'issued':
        flash('Книга не находится на выдаче', 'error')
        return redirect(url_for('catalog'))

    loan = db.execute(
        'SELECT * FROM loans WHERE book_id = ? AND returned_at IS NULL ORDER BY id DESC LIMIT 1',
        (book_id,)
    ).fetchone()
    if loan:
        db.execute(
            'UPDATE loans SET returned_at = ? WHERE id = ?',
            (datetime.now().strftime('%Y-%m-%d'), loan['id'])
        )
    db.execute('UPDATE books SET status = ? WHERE id = ?', ('available', book_id))
    log_operation('Возврат', book['title'], None, session['login'])
    db.commit()
    flash('Книга «%s» возвращена' % book['title'], 'success')
    return redirect(url_for('catalog'))


# ---------- Читатели ----------

@app.route('/readers')
@staff_required
def readers():
    db = get_db()
    search = request.args.get('search', '').strip()

    query = '''
        SELECT r.*,
               (SELECT COUNT(*) FROM loans l WHERE l.reader_id = r.id) AS loans_count,
               (SELECT COUNT(*) FROM loans l WHERE l.reader_id = r.id
                    AND l.returned_at IS NULL AND l.due_at < date('now')) AS overdue_count
        FROM readers r WHERE 1=1
    '''
    params = []
    if search:
        query += ' AND (r.full_name LIKE ? OR r.phone LIKE ?)'
        params.extend(['%' + search + '%', '%' + search + '%'])
    query += ' ORDER BY r.full_name'

    all_readers = db.execute(query, params).fetchall()
    return render_template('readers.html', readers=all_readers,
                           search=search, page='readers')


@app.route('/readers/add', methods=['POST'])
@staff_required
def add_reader():
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()

    if not full_name or not phone:
        flash('Заполните все обязательные поля', 'error')
        return redirect(url_for('readers'))

    db = get_db()
    db.execute('INSERT INTO readers (full_name, phone) VALUES (?, ?)', (full_name, phone))
    log_operation('Регистрация читателя', None, full_name, session['login'])
    db.commit()
    flash('Читатель «%s» зарегистрирован' % full_name, 'success')
    return redirect(url_for('readers'))


# ---------- Выдача и возврат ----------

@app.route('/circulation')
@staff_required
def circulation():
    db = get_db()
    books = db.execute('SELECT * FROM books ORDER BY title').fetchall()
    all_readers = db.execute('SELECT * FROM readers ORDER BY full_name').fetchall()
    return render_template('circulation.html', books=books,
                           readers=all_readers, page='circulation')


@app.route('/circulation/issue', methods=['POST'])
@staff_required
def circulation_issue():
    book_id = request.form.get('book_id')
    reader_id = request.form.get('reader_id')
    issued_at = request.form.get('issued_at')
    due_at = request.form.get('due_at')
    employee = session['login']

    if not book_id or not reader_id or not issued_at or not due_at:
        flash('Заполните все обязательные поля', 'error')
        return redirect(url_for('circulation'))

    db = get_db()
    book = db.execute('SELECT * FROM books WHERE id = ?', (book_id,)).fetchone()
    reader = db.execute('SELECT * FROM readers WHERE id = ?', (reader_id,)).fetchone()

    if book is None or book['status'] != 'available':
        flash('Книга недоступна для выдачи', 'error')
        return redirect(url_for('circulation'))
    if reader is None:
        flash('Читатель не найден', 'error')
        return redirect(url_for('circulation'))

    db.execute(
        'INSERT INTO loans (book_id, reader_id, employee, issued_at, due_at) VALUES (?, ?, ?, ?, ?)',
        (book_id, reader_id, employee, issued_at, due_at)
    )
    db.execute('UPDATE books SET status = ? WHERE id = ?', ('issued', book_id))
    log_operation('Выдача', book['title'], reader['full_name'], employee)
    db.commit()
    flash('Книга «%s» выдана читателю %s' % (book['title'], reader['full_name']), 'success')
    return redirect(url_for('circulation'))


@app.route('/circulation/return', methods=['POST'])
@staff_required
def circulation_return():
    book_id = request.form.get('book_id')
    employee = session['login']

    if not book_id:
        flash('Выберите книгу для возврата', 'error')
        return redirect(url_for('circulation'))

    db = get_db()
    book = db.execute('SELECT * FROM books WHERE id = ?', (book_id,)).fetchone()
    if book is None or book['status'] != 'issued':
        flash('Книга не находится на выдаче', 'error')
        return redirect(url_for('circulation'))

    loan = db.execute(
        'SELECT * FROM loans WHERE book_id = ? AND returned_at IS NULL ORDER BY id DESC LIMIT 1',
        (book_id,)
    ).fetchone()
    if loan:
        db.execute(
            'UPDATE loans SET returned_at = ? WHERE id = ?',
            (datetime.now().strftime('%Y-%m-%d'), loan['id'])
        )
    db.execute('UPDATE books SET status = ? WHERE id = ?', ('available', book_id))
    log_operation('Возврат', book['title'], None, employee)
    db.commit()
    flash('Книга «%s» возвращена' % book['title'], 'success')
    return redirect(url_for('circulation'))


# ---------- Просрочки ----------

@app.route('/overdue')
@staff_required
def overdue():
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    rows = db.execute('''
        SELECT r.full_name, r.phone, b.title, l.due_at
        FROM loans l
        JOIN readers r ON r.id = l.reader_id
        JOIN books b ON b.id = l.book_id
        WHERE l.returned_at IS NULL AND l.due_at < ?
        ORDER BY l.due_at
    ''', (today,)).fetchall()

    overdue_list = []
    for row in rows:
        due = datetime.strptime(row['due_at'], '%Y-%m-%d')
        days = (datetime.now() - due).days
        overdue_list.append({
            'full_name': row['full_name'],
            'phone': row['phone'],
            'title': row['title'],
            'due_at': row['due_at'],
            'days': days
        })
    return render_template('overdue.html', overdue_list=overdue_list, page='overdue')


# ---------- Отчёты ----------

@app.route('/reports')
@staff_required
def reports():
    return render_template('reports.html', page='reports')


@app.route('/reports/export/<report_type>')
@staff_required
def export_report(report_type):
    db = get_db()
    lines = []

    if report_type == 'loans':
        rows = db.execute('''
            SELECT l.id, b.title, b.author, r.full_name, l.employee,
                   l.issued_at, l.due_at, COALESCE(l.returned_at, '-')
            FROM loans l
            JOIN books b ON b.id = l.book_id
            JOIN readers r ON r.id = l.reader_id
            ORDER BY l.issued_at
        ''').fetchall()
        lines.append('ID;Книга;Автор;Читатель;Сотрудник;Выдана;Срок;Возвращена')
        for row in rows:
            lines.append(';'.join(str(x) for x in tuple(row)))
        filename = 'report_loans.csv'
    elif report_type == 'fund':
        rows = db.execute(
            'SELECT id, title, author, genre, year, status FROM books ORDER BY title'
        ).fetchall()
        lines.append('ID;Название;Автор;Жанр;Год;Статус')
        for row in rows:
            lines.append(';'.join(str(x) for x in tuple(row)))
        filename = 'report_fund.csv'
    else:
        flash('Неизвестный тип отчёта', 'error')
        return redirect(url_for('reports'))

    csv_text = '\n'.join(lines)
    return Response(
        '\ufeff' + csv_text,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=%s' % filename}
    )


# ---------- Администрирование ----------

@app.route('/admin')
@admin_required
def admin():
    db = get_db()
    users = db.execute('SELECT * FROM users ORDER BY login').fetchall()
    return render_template('admin.html', users=users, page='admin')


@app.route('/admin/unblock/<int:user_id>', methods=['POST'])
@admin_required
def unblock_user(user_id):
    db = get_db()
    db.execute('UPDATE users SET is_blocked = 0, failed_attempts = 0 WHERE id = ?', (user_id,))
    db.commit()
    flash('Пользователь разблокирован', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/reset_attempts/<int:user_id>', methods=['POST'])
@admin_required
def reset_attempts(user_id):
    db = get_db()
    db.execute('UPDATE users SET failed_attempts = 0 WHERE id = ?', (user_id,))
    db.commit()
    flash('Счётчик попыток сброшен', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/add_user', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        login_name = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')

        if not login_name or not password:
            flash('Заполните все обязательные поля', 'error')
            return render_template('add_user.html')

        if role not in ('user', 'admin', 'reader'):
            role = 'user'

        db = get_db()
        exists = db.execute('SELECT id FROM users WHERE login = ?', (login_name,)).fetchone()
        if exists:
            flash('Пользователь с логином «%s» уже существует' % login_name, 'error')
            return render_template('add_user.html')

        db.execute(
            'INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, 1)',
            (login_name, generate_password_hash(password), role)
        )
        db.commit()
        flash('Пользователь «%s» создан. При первом входе он обязан сменить пароль' % login_name, 'success')
        return redirect(url_for('admin'))

    return render_template('add_user.html', page='add_user')


# ---------- Запуск ----------

if __name__ == '__main__':
    init_db()
    print('=' * 60)
    print('URUS — Библиотечный учёт')
    print('Адрес: http://127.0.0.1:5000')
    print('Администратор: логин admin, пароль admin123')
    print('=' * 60)
    app.run(debug=True, host='127.0.0.1', port=5000)
