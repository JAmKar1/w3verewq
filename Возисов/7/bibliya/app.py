from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = 'urus-secret-key-change-in-production'

DB_PATH = 'urus.db'

# ================= ИНИЦИАЛИЗАЦИЯ БД =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        login TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        is_blocked INTEGER DEFAULT 0,
        failed_attempts INTEGER DEFAULT 0,
        first_login INTEGER DEFAULT 1,
        last_login TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Создаём администратора по умолчанию
    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, ?)",
                  ('admin', generate_password_hash('admin123'), 'admin', 0))
        print('Создан администратор: admin / admin123')
    
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
def is_logged_in():
    return 'user_id' in session

def is_admin():
    return session.get('role') == 'admin'

def check_auto_block():
    """Блокировка если не входил более 1 месяца"""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    conn.close()
    
    if user and user['last_login'] and not user['is_blocked']:
        last = datetime.fromisoformat(user['last_login'])
        if datetime.now() - last > timedelta(days=30):
            conn = get_db()
            conn.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (session['user_id'],))
            conn.commit()
            conn.close()
            return True
    return False

# ================= МАРШРУТЫ =================
@app.route('/')
def index():
    if is_logged_in():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form.get('login', '').strip()
        password = request.form.get('password', '').strip()
        
        # Проверка обязательных полей
        if not login_input or not password:
            flash('Заполните все поля', 'error')
            return render_template('login.html')
        
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE login = ?", (login_input,)).fetchone()
        
        # Пользователь не найден
        if not user:
            flash('Вы ввели неверный логин или пароль. Пожалуйста проверьте ещё раз введенные данные', 'error')
            conn.close()
            return render_template('login.html')
        
        # Аккаунт заблокирован
        if user['is_blocked']:
            flash('Вы заблокированы. Обратитесь к администратору', 'error')
            conn.close()
            return render_template('login.html')
        
        # Проверка пароля
        if check_password_hash(user['password_hash'], password):
            # Успешный вход
            conn.execute("UPDATE users SET failed_attempts = 0, last_login = ? WHERE id = ?",
                        (datetime.now().isoformat(), user['id']))
            conn.commit()
            
            session['user_id'] = user['id']
            session['login'] = user['login']
            session['role'] = user['role']
            
            # Первый вход — смена пароля
            if user['first_login']:
                flash('Вы успешно авторизовались. Смените пароль при первом входе.', 'success')
                conn.close()
                return redirect(url_for('change_password'))
            
            flash('Вы успешно авторизовались', 'success')
            conn.close()
            return redirect(url_for('dashboard'))
        else:
            # Неверный пароль
            failed = user['failed_attempts'] + 1
            if failed >= 3:
                conn.execute("UPDATE users SET failed_attempts = ?, is_blocked = 1 WHERE id = ?",
                            (failed, user['id']))
                conn.commit()
                flash('Вы заблокированы. Обратитесь к администратору', 'error')
            else:
                conn.execute("UPDATE users SET failed_attempts = ? WHERE id = ?",
                            (failed, user['id']))
                conn.commit()
                flash(f'Вы ввели неверный логин или пароль. Осталось попыток: {3 - failed}', 'error')
            conn.close()
            return render_template('login.html')
    
    return render_template('login.html')

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        current = request.form.get('current_password', '').strip()
        new = request.form.get('new_password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()
        
        # Проверка обязательных полей
        if not current or not new or not confirm:
            flash('Заполните все поля', 'error')
            return render_template('change_password.html')
        
        # Проверка совпадения нового пароля
        if new != confirm:
            flash('Новый пароль и подтверждение не совпадают', 'error')
            return render_template('change_password.html')
        
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        
        # Проверка текущего пароля
        if not check_password_hash(user['password_hash'], current):
            flash('Неверный текущий пароль', 'error')
            conn.close()
            return render_template('change_password.html')
        
        # Обновление пароля
        conn.execute("UPDATE users SET password_hash = ?, first_login = 0 WHERE id = ?",
                    (generate_password_hash(new), session['user_id']))
        conn.commit()
        conn.close()
        
        flash('Пароль успешно изменён', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('change_password.html')

@app.route('/dashboard')
def dashboard():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    # Проверка автоматической блокировки (1 месяц)
    if check_auto_block():
        session.clear()
        flash('Вы заблокированы. Обратитесь к администратору', 'error')
        return redirect(url_for('login'))
    
    return render_template('dashboard.html')

@app.route('/admin')
def admin():
    if not is_logged_in():
        return redirect(url_for('login'))
    if not is_admin():
        flash('Доступ запрещён', 'error')
        return redirect(url_for('dashboard'))
    
    conn = get_db()
    users = conn.execute("SELECT * FROM users ORDER BY login").fetchall()
    conn.close()
    return render_template('admin.html', users=users)

@app.route('/admin/add_user', methods=['GET', 'POST'])
def add_user():
    if not is_logged_in() or not is_admin():
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        login_input = request.form.get('login', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'user')
        
        if not login_input or not password:
            flash('Заполните все поля', 'error')
            return render_template('add_user.html')
        
        conn = get_db()
        existing = conn.execute("SELECT * FROM users WHERE login = ?", (login_input,)).fetchone()
        
        if existing:
            flash(f'Пользователь с логином «{login_input}» уже существует', 'error')
            conn.close()
            return render_template('add_user.html')
        
        conn.execute("INSERT INTO users (login, password_hash, role, first_login) VALUES (?, ?, ?, 1)",
                    (login_input, generate_password_hash(password), role))
        conn.commit()
        conn.close()
        
        flash(f'Пользователь «{login_input}» создан. Пароль: {password}', 'success')
        return redirect(url_for('admin'))
    
    return render_template('add_user.html')

@app.route('/admin/unblock/<int:user_id>')
def unblock_user(user_id):
    if not is_logged_in() or not is_admin():
        return redirect(url_for('login'))
    
    conn = get_db()
    conn.execute("UPDATE users SET is_blocked = 0, failed_attempts = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash('Пользователь разблокирован', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/reset_attempts/<int:user_id>')
def reset_attempts(user_id):
    if not is_logged_in() or not is_admin():
        return redirect(url_for('login'))
    
    conn = get_db()
    conn.execute("UPDATE users SET failed_attempts = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash('Счётчик попыток сброшен', 'success')
    return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('login'))

# ================= ЗАПУСК =================
if __name__ == '__main__':
    init_db()
    print('=' * 50)
    print('URUS — Библиотечный учёт')
    print('Откройте: http://127.0.0.1:5000')
    print('Админ: admin / admin123')
    print('=' * 50)
    app.run(debug=True, host='127.0.0.1', port=5000)