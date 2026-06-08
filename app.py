from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import sqlite3
from datetime import datetime, date
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = 'pronostici-secret-key-2024'
app.jinja_env.globals['enumerate'] = enumerate

DB_PATH = os.path.join(os.path.dirname(__file__), 'pronostici.db')

# ─── DB INIT ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS utenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS giornate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            data TEXT NOT NULL,
            chiusa INTEGER DEFAULT 0,
            chiusura_automatica TEXT
        );
        -- Migrazione: aggiungi colonna se non esiste
        

        CREATE TABLE IF NOT EXISTS partite (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giornata_id INTEGER NOT NULL,
            squadra_casa TEXT NOT NULL,
            squadra_ospite TEXT NOT NULL,
            risultato TEXT,
            ordine INTEGER DEFAULT 0,
            FOREIGN KEY(giornata_id) REFERENCES giornate(id)
        );

        CREATE TABLE IF NOT EXISTS pronostici (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            partita_id INTEGER NOT NULL,
            pronostico TEXT NOT NULL CHECK(pronostico IN ('1','X','2')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(utente_id, partita_id),
            FOREIGN KEY(utente_id) REFERENCES utenti(id),
            FOREIGN KEY(partita_id) REFERENCES partite(id)
        );

        CREATE TABLE IF NOT EXISTS classifica (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            giornata_id INTEGER NOT NULL,
            punti INTEGER DEFAULT 0,
            UNIQUE(utente_id, giornata_id),
            FOREIGN KEY(utente_id) REFERENCES utenti(id),
            FOREIGN KEY(giornata_id) REFERENCES giornate(id)
        );
    ''')
    # Migrazione: aggiungi colonna chiusura_automatica se non esiste
    try:
        c.execute("ALTER TABLE giornate ADD COLUMN chiusura_automatica TEXT")
        conn.commit()
    except Exception:
        pass  # colonna già esistente
    # Crea admin di default se non esiste
    c.execute("SELECT id FROM utenti WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO utenti(username, password, is_admin) VALUES(?,?,1)",
                  ('admin', 'admin123'))
    conn.commit()
    conn.close()

def chiudi_giornate_scadute():
    """Chiude automaticamente le giornate il cui orario di chiusura è passato."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn = get_db()
    conn.execute("""
        UPDATE giornate SET chiusa=1
        WHERE chiusa=0
        AND chiusura_automatica IS NOT NULL
        AND chiusura_automatica != ''
        AND chiusura_automatica <= ?
    """, (now,))
    conn.commit()
    conn.close()

# ─── AUTH ───────────────────────────────────────────────────────────────────────

@app.before_request
def controlla_chiusure():
    chiudi_giornate_scadute()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

# ─── AUTH ROUTES ───────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM utenti WHERE username=? AND password=?",
                            (username, password)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            if user['is_admin']:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        flash('Credenziali non valide', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/registrati', methods=['GET','POST'])
def registrati():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        if not username or not password:
            flash('Compila tutti i campi', 'error')
            return render_template('registrati.html')
        conn = get_db()
        try:
            conn.execute("INSERT INTO utenti(username, password) VALUES(?,?)", (username, password))
            conn.commit()
            flash('Registrazione avvenuta! Ora puoi accedere.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username già in uso', 'error')
        finally:
            conn.close()
    return render_template('registrati.html')

# ─── FRONTEND UTENTE ────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    conn = get_db()
    giornate = conn.execute(
        "SELECT * FROM giornate WHERE chiusa=0 ORDER BY data DESC"
    ).fetchall()
    conn.close()
    return render_template('index.html', giornate=giornate)

@app.route('/giornata/<int:gid>')
@login_required
def giornata(gid):
    conn = get_db()
    giornata = conn.execute("SELECT * FROM giornate WHERE id=?", (gid,)).fetchone()
    if not giornata:
        return redirect(url_for('index'))
    partite = conn.execute(
        "SELECT * FROM partite WHERE giornata_id=? ORDER BY ordine", (gid,)
    ).fetchall()
    # Pronostici già inseriti dall'utente per questa giornata
    miei = {}
    for p in conn.execute(
        """SELECT pr.partita_id, pr.pronostico
           FROM pronostici pr
           JOIN partite pt ON pt.id = pr.partita_id
           WHERE pr.utente_id=? AND pt.giornata_id=?""",
        (session['user_id'], gid)
    ).fetchall():
        miei[p['partita_id']] = p['pronostico']
    gia_salvato = len(miei) > 0
    conn.close()
    return render_template('giornata.html', giornata=giornata, partite=partite, miei=miei, gia_salvato=gia_salvato)

@app.route('/salva_pronostici', methods=['POST'])
@login_required
def salva_pronostici():
    data = request.get_json()
    gid = data.get('giornata_id')
    pronostici = data.get('pronostici', {})
    conn = get_db()
    # Verifica che la giornata sia aperta
    g = conn.execute("SELECT chiusa FROM giornate WHERE id=?", (gid,)).fetchone()
    if not g or g['chiusa']:
        conn.close()
        return jsonify({'ok': False, 'msg': 'Giornata chiusa'}), 400
    # Verifica che l'utente non abbia già salvato pronostici per questa giornata
    esistenti = conn.execute('''
        SELECT COUNT(*) FROM pronostici p
        JOIN partite pt ON pt.id = p.partita_id
        WHERE p.utente_id=? AND pt.giornata_id=?
    ''', (session['user_id'], gid)).fetchone()[0]
    if esistenti > 0:
        conn.close()
        return jsonify({'ok': False, 'msg': 'Hai già salvato i pronostici per questa giornata'}), 403
    for partita_id, val in pronostici.items():
        if val not in ('1','X','2'):
            continue
        conn.execute('''
            INSERT INTO pronostici(utente_id, partita_id, pronostico)
            VALUES(?,?,?)
            ON CONFLICT(utente_id, partita_id) DO UPDATE SET pronostico=excluded.pronostico
        ''', (session['user_id'], int(partita_id), val))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/classifica_generale')
@login_required
def classifica_generale():
    conn = get_db()
    rows = conn.execute('''
        SELECT u.username,
               COALESCE(SUM(c.punti),0) as totale,
               COUNT(DISTINCT c.giornata_id) as giornate
        FROM utenti u
        LEFT JOIN classifica c ON c.utente_id=u.id
        WHERE u.is_admin=0
        GROUP BY u.id
        ORDER BY totale DESC
    ''').fetchall()
    conn.close()
    return render_template('classifica.html', rows=rows)

# ─── BACKOFFICE ─────────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    giornate = conn.execute("SELECT * FROM giornate ORDER BY data DESC").fetchall()
    n_utenti = conn.execute("SELECT COUNT(*) FROM utenti WHERE is_admin=0").fetchone()[0]
    conn.close()
    return render_template('admin/dashboard.html', giornate=giornate, n_utenti=n_utenti)

@app.route('/admin/giornata/nuova', methods=['GET','POST'])
@admin_required
def nuova_giornata():
    if request.method == 'POST':
        nome = request.form.get('nome','').strip()
        data_g = request.form.get('data','').strip()
        conn = get_db()
        chiusura = request.form.get('chiusura_automatica','').strip()
        chiusura_dt = None
        if chiusura:
            chiusura_dt = data_g + ' ' + chiusura
        cur = conn.execute("INSERT INTO giornate(nome, data, chiusura_automatica) VALUES(?,?,?)", (nome, data_g, chiusura_dt))
        conn.commit()
        gid = cur.lastrowid
        conn.close()
        return redirect(url_for('gestisci_giornata', gid=gid))
    return render_template('admin/nuova_giornata.html', oggi=date.today().isoformat())

@app.route('/admin/giornata/<int:gid>', methods=['GET','POST'])
@admin_required
def gestisci_giornata(gid):
    conn = get_db()
    giornata = conn.execute("SELECT * FROM giornate WHERE id=?", (gid,)).fetchone()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'aggiungi_partita':
            casa = request.form.get('casa','').strip()
            ospite = request.form.get('ospite','').strip()
            ordine = conn.execute(
                "SELECT COALESCE(MAX(ordine),0)+1 FROM partite WHERE giornata_id=?", (gid,)
            ).fetchone()[0]
            conn.execute("INSERT INTO partite(giornata_id, squadra_casa, squadra_ospite, ordine) VALUES(?,?,?,?)",
                         (gid, casa, ospite, ordine))
            conn.commit()
        elif action == 'elimina_partita':
            pid = request.form.get('partita_id')
            conn.execute("DELETE FROM partite WHERE id=?", (pid,))
            conn.commit()
        elif action == 'toggle_chiudi':
            stato = 1 - (giornata['chiusa'] or 0)
            conn.execute("UPDATE giornate SET chiusa=? WHERE id=?", (stato, gid))
            conn.commit()
            giornata = conn.execute("SELECT * FROM giornate WHERE id=?", (gid,)).fetchone()
        elif action == 'imposta_chiusura':
            data_c = request.form.get('data_chiusura','').strip()
            ora_c = request.form.get('ora_chiusura','').strip()
            if data_c and ora_c:
                chiusura_dt = data_c + ' ' + ora_c
            else:
                chiusura_dt = None
            conn.execute("UPDATE giornate SET chiusura_automatica=? WHERE id=?", (chiusura_dt, gid))
            conn.commit()
            giornata = conn.execute("SELECT * FROM giornate WHERE id=?", (gid,)).fetchone()
            flash('Chiusura automatica impostata!' if chiusura_dt else 'Chiusura automatica rimossa.', 'success')
        elif action == 'elimina_giornata':
            conn.execute("DELETE FROM pronostici WHERE partita_id IN (SELECT id FROM partite WHERE giornata_id=?)", (gid,))
            conn.execute("DELETE FROM partite WHERE giornata_id=?", (gid,))
            conn.execute("DELETE FROM classifica WHERE giornata_id=?", (gid,))
            conn.execute("DELETE FROM giornate WHERE id=?", (gid,))
            conn.commit()
            conn.close()
            return redirect(url_for('admin_dashboard'))
    partite = conn.execute("SELECT * FROM partite WHERE giornata_id=? ORDER BY ordine", (gid,)).fetchall()
    conn.close()
    return render_template('admin/gestisci_giornata.html', giornata=giornata, partite=partite)

@app.route('/admin/giornata/<int:gid>/risultati', methods=['GET','POST'])
@admin_required
def risultati_giornata(gid):
    conn = get_db()
    giornata = conn.execute("SELECT * FROM giornate WHERE id=?", (gid,)).fetchone()
    partite = conn.execute("SELECT * FROM partite WHERE giornata_id=? ORDER BY ordine", (gid,)).fetchall()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'salva_risultati':
            for p in partite:
                r = request.form.get(f'risultato_{p["id"]}','').strip()
                if r in ('1','X','2',''):
                    conn.execute("UPDATE partite SET risultato=? WHERE id=?", (r or None, p['id']))
            conn.commit()
            partite = conn.execute("SELECT * FROM partite WHERE giornata_id=? ORDER BY ordine", (gid,)).fetchall()
        elif action == 'calcola_classifica':
            # Calcola punti per ogni utente su questa giornata
            utenti = conn.execute("SELECT id FROM utenti WHERE is_admin=0").fetchall()
            for u in utenti:
                punti = 0
                for p in partite:
                    if not p['risultato']:
                        continue
                    pron = conn.execute(
                        "SELECT pronostico FROM pronostici WHERE utente_id=? AND partita_id=?",
                        (u['id'], p['id'])
                    ).fetchone()
                    if pron and pron['pronostico'] == p['risultato']:
                        punti += 1
                conn.execute('''
                    INSERT INTO classifica(utente_id, giornata_id, punti)
                    VALUES(?,?,?)
                    ON CONFLICT(utente_id, giornata_id) DO UPDATE SET punti=excluded.punti
                ''', (u['id'], gid, punti))
            conn.commit()
            flash('Classifica calcolata!', 'success')

    # Tutti i pronostici degli utenti
    utenti_pronostici = []
    utenti = conn.execute("SELECT id, username FROM utenti WHERE is_admin=0 ORDER BY username").fetchall()
    for u in utenti:
        prons = {}
        for row in conn.execute(
            "SELECT partita_id, pronostico FROM pronostici WHERE utente_id=?", (u['id'],)
        ).fetchall():
            prons[row['partita_id']] = row['pronostico']
        punti_row = conn.execute(
            "SELECT punti FROM classifica WHERE utente_id=? AND giornata_id=?", (u['id'], gid)
        ).fetchone()
        utenti_pronostici.append({
            'username': u['username'],
            'pronostici': prons,
            'punti': punti_row['punti'] if punti_row else '-'
        })
    conn.close()
    return render_template('admin/risultati.html',
                           giornata=giornata, partite=partite,
                           utenti_pronostici=utenti_pronostici)

@app.route('/admin/classifica')
@admin_required
def admin_classifica():
    conn = get_db()
    giornate = conn.execute("SELECT * FROM giornate ORDER BY data DESC").fetchall()
    rows = conn.execute('''
        SELECT u.username,
               COALESCE(SUM(c.punti),0) as totale,
               COUNT(DISTINCT c.giornata_id) as giornate_giocate
        FROM utenti u
        LEFT JOIN classifica c ON c.utente_id=u.id
        WHERE u.is_admin=0
        GROUP BY u.id
        ORDER BY totale DESC
    ''').fetchall()
    # Per giornata
    classifica_per_giornata = []
    for g in giornate:
        righe = conn.execute('''
            SELECT u.username, COALESCE(c.punti,0) as punti
            FROM utenti u
            LEFT JOIN classifica c ON c.utente_id=u.id AND c.giornata_id=?
            WHERE u.is_admin=0
            ORDER BY punti DESC
        ''', (g['id'],)).fetchall()
        classifica_per_giornata.append({'giornata': g, 'righe': righe})
    conn.close()
    return render_template('admin/classifica.html', rows=rows, classifica_per_giornata=classifica_per_giornata)

@app.route('/admin/utenti')
@admin_required
def admin_utenti():
    conn = get_db()
    utenti = conn.execute("SELECT * FROM utenti WHERE is_admin=0 ORDER BY username").fetchall()
    conn.close()
    return render_template('admin/utenti.html', utenti=utenti)

@app.route('/admin/utenti/elimina/<int:uid>', methods=['POST'])
@admin_required
def elimina_utente(uid):
    conn = get_db()
    conn.execute("DELETE FROM pronostici WHERE utente_id=?", (uid,))
    conn.execute("DELETE FROM classifica WHERE utente_id=?", (uid,))
    conn.execute("DELETE FROM utenti WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_utenti'))


@app.route('/admin/utenti/cambio_password', methods=['POST'])
@admin_required
def admin_cambio_password():
    data = request.get_json()
    uid = data.get('utente_id')
    nuova = data.get('password', '').strip()
    if not nuova:
        return jsonify({'ok': False, 'msg': 'Password vuota'})
    conn = get_db()
    conn.execute("UPDATE utenti SET password=? WHERE id=? AND is_admin=0", (nuova, uid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/profilo', methods=['GET', 'POST'])
@login_required
def profilo():
    if request.method == 'POST':
        attuale = request.form.get('password_attuale', '').strip()
        nuova = request.form.get('password_nuova', '').strip()
        conferma = request.form.get('password_conferma', '').strip()
        conn = get_db()
        utente = conn.execute("SELECT * FROM utenti WHERE id=?", (session['user_id'],)).fetchone()
        if utente['password'] != attuale:
            flash('Password attuale non corretta', 'error')
        elif not nuova:
            flash('La nuova password non può essere vuota', 'error')
        elif nuova != conferma:
            flash('Le password non coincidono', 'error')
        else:
            conn.execute("UPDATE utenti SET password=? WHERE id=?", (nuova, session['user_id']))
            conn.commit()
            flash('Password aggiornata con successo!', 'success')
        conn.close()
    return render_template('profilo.html')

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
