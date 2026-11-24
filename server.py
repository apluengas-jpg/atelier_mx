"""ATELIER · deployable Flask app. Configure secrets and Stripe to enable live billing."""
import os, json, sqlite3, secrets, time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from flask import Flask, request, jsonify, session, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

ROOT=Path(__file__).parent
app=Flask(__name__,static_folder='static',static_url_path='/static')
app.secret_key=os.environ.get('SECRET_KEY',secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','0')=='1',MAX_CONTENT_LENGTH=1024*1024)
limiter=Limiter(get_remote_address,app=app,default_limits=['180 per minute'],storage_uri=os.environ.get('RATELIMIT_STORAGE_URI','memory://'))
DB=os.environ.get('DATABASE_PATH',str(ROOT/'atelier.db'))
PLANS={'artist':{'name':'Artista','monthly':150,'semiannual':800,'annual':1400,'role':'artist'},'venue':{'name':'Negocio','monthly':250,'semiannual':1300,'annual':2200,'role':'venue'}}

def conn():
 c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c

def init():
 with conn() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'public',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS profiles(id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE REFERENCES users(id),bio TEXT DEFAULT '',claimed_entity TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS favorites(user_id INTEGER REFERENCES users(id),entity_type TEXT,entity_id TEXT,PRIMARY KEY(user_id,entity_type,entity_id));
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS collaborations(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),entity_type TEXT,entity_id TEXT,message TEXT NOT NULL,status TEXT DEFAULT 'new',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE REFERENCES users(id),plan TEXT,status TEXT DEFAULT 'inactive',stripe_customer_id TEXT,stripe_subscription_id TEXT UNIQUE,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT,starts_at TEXT,ends_at TEXT,venue_id TEXT,location_name TEXT,address TEXT,description TEXT,price TEXT,source_url TEXT,source_name TEXT,status TEXT,lat REAL,lng REAL,submitted_by INTEGER,approved INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),entity_type TEXT,entity_id TEXT,evidence TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS webhook_events(event_id TEXT PRIMARY KEY,processed_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
  if c.execute('SELECT count(*) FROM events').fetchone()[0]==0:
   for e in json.loads((ROOT/'events.json').read_text()):
    c.execute('INSERT INTO events(id,name,category,starts_at,venue_id,description,price,source_name,status,approved) VALUES(?,?,?,?,?,?,?,?,?,1)',(e['id'],e['name'],e['category'],e['date']+'T'+(e['time'] or '00:00') if e['date'] else None,e['venue'],e['bio'],e['price'],e['source'],'Archivo'))
  for e in json.loads((ROOT/'researched_events.json').read_text()):
   c.execute('INSERT OR IGNORE INTO events(id,name,category,starts_at,ends_at,venue_id,location_name,address,description,price,source_url,source_name,status,approved) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)',(e['id'],e['name'],e['category'],e.get('starts_at'),e.get('ends_at'),e.get('venue_id'),e['location_name'],e['address'],e['description'],e['price'],e['source_url'],e['source_name'],e['status']))
init()

def current_user():
 uid=session.get('uid')
 if not uid:return None
 with conn() as c:
  row=c.execute('SELECT id,email,name,role FROM users WHERE id=?',(uid,)).fetchone()
  if not row:return None
  sub=c.execute('SELECT plan,status FROM subscriptions WHERE user_id=?',(uid,)).fetchone()
  profile=c.execute('SELECT bio FROM profiles WHERE user_id=?',(uid,)).fetchone()
  return {**dict(row),'bio':profile['bio'] if profile else '', 'membership':dict(sub) if sub else None}

def auth(fn):
 @wraps(fn)
 def wrapper(*a,**kw):
  if not current_user():return jsonify(error='Inicia sesión para continuar'),401
  return fn(*a,**kw)
 return wrapper

def csrf_check():
 if request.method in ('POST','PUT','PATCH','DELETE') and request.path not in ('/api/stripe/webhook',):
  if not session.get('csrf') or request.headers.get('X-CSRF-Token')!=session.get('csrf'):return jsonify(error='Sesión no válida. Actualiza la página.'),403
app.before_request(csrf_check)

def data():return request.get_json(silent=True) or {}
def err(msg,code=400):return jsonify(error=msg),code

@app.get('/')
def index():return send_from_directory(ROOT/'static','index.html')
@app.get('/api/bootstrap')
def bootstrap():
 session.setdefault('csrf',secrets.token_urlsafe(24))
 with conn() as c: ev=[dict(r) for r in c.execute('SELECT * FROM events WHERE approved=1 ORDER BY starts_at DESC')]
 return jsonify(csrf=session['csrf'],user=current_user(),artists=json.loads((ROOT/'artists.json').read_text()),venues=json.loads((ROOT/'venues.json').read_text())+json.loads((ROOT/'researched_venues.json').read_text()),events=ev,plans=PLANS,billing_enabled=bool(os.environ.get('STRIPE_SECRET_KEY')))

@app.post('/api/register')
@limiter.limit('5 per hour')
def register():
 d=data();email=str(d.get('email','')).strip().lower();name=str(d.get('name','')).strip();pw=str(d.get('password',''));role=d.get('role','public')
 if '@' not in email or len(email)>150 or len(name)<2 or len(name)>90 or len(pw)<10 or role not in ('public','artist','venue'):return err('Revisa tus datos. La contraseña requiere al menos 10 caracteres.')
 if role!='public' and d.get('period') not in ('monthly','semiannual','annual'):return err('Selecciona una membresía obligatoria.')
 try:
  with conn() as c:
   cur=c.execute('INSERT INTO users(email,name,password_hash,role) VALUES(?,?,?,?)',(email,name,generate_password_hash(pw),role));c.execute('INSERT INTO profiles(user_id,bio) VALUES(?,?)',(cur.lastrowid,str(d.get('bio',''))[:2000]));session.clear();session['uid']=cur.lastrowid;session['csrf']=secrets.token_urlsafe(24)
   if role!='public':c.execute('INSERT INTO subscriptions(user_id,plan,status) VALUES(?,?,?)',(cur.lastrowid,role+':'+d['period'],'pending'))
 except sqlite3.IntegrityError:return err('Ese correo ya está registrado',409)
 return jsonify(user=current_user(),csrf=session['csrf'])

@app.post('/api/login')
@limiter.limit('12 per hour')
def login():
 d=data()
 with conn() as c:r=c.execute('SELECT * FROM users WHERE email=?',(str(d.get('email','')).lower().strip(),)).fetchone()
 if not r or not check_password_hash(r['password_hash'],str(d.get('password',''))):return err('Credenciales incorrectas',401)
 session.clear();session['uid']=r['id'];session['csrf']=secrets.token_urlsafe(24)
 return jsonify(user=current_user(),csrf=session['csrf'])
@app.post('/api/logout')
def logout():session.clear();return jsonify(ok=True)

@app.get('/api/me')
@auth
def me():
 u=current_user()
 with conn() as c:
  fav=[dict(r) for r in c.execute('SELECT entity_type,entity_id FROM favorites WHERE user_id=?',(u['id'],))]
  reviews=[dict(r) for r in c.execute('SELECT * FROM reviews WHERE user_id=? ORDER BY id DESC',(u['id'],))]
  collabs=[dict(r) for r in c.execute('SELECT * FROM collaborations WHERE user_id=? ORDER BY id DESC',(u['id'],))]
 return jsonify(user=u,favorites=fav,reviews=reviews,collaborations=collabs)

@app.post('/api/favorites')
@auth
def favorite():
 d=data();typ=d.get('type');eid=str(d.get('id',''))
 if typ not in ('artist','venue','event') or len(eid)>100:return err('Ficha inválida')
 with conn() as c:
  row=c.execute('SELECT 1 FROM favorites WHERE user_id=? AND entity_type=? AND entity_id=?',(session['uid'],typ,eid)).fetchone()
  if row:c.execute('DELETE FROM favorites WHERE user_id=? AND entity_type=? AND entity_id=?',(session['uid'],typ,eid))
  else:c.execute('INSERT INTO favorites VALUES(?,?,?)',(session['uid'],typ,eid))
 return jsonify(saved=not bool(row))

@app.get('/api/reviews')
def reviews():
 typ=request.args.get('type');eid=request.args.get('id')
 with conn() as c:r=[dict(x) for x in c.execute('SELECT reviews.id,reviews.user_id,reviews.rating,reviews.body,reviews.created_at,users.name FROM reviews JOIN users ON users.id=reviews.user_id WHERE reviews.entity_type=? AND reviews.entity_id=? AND reviews.status="approved" ORDER BY reviews.id DESC LIMIT 100',(typ,eid))]
 return jsonify(reviews=r)
@app.post('/api/reviews')
@auth
@limiter.limit('10 per day')
def add_review():
 d=data();body=str(d.get('body','')).strip();typ=d.get('type');eid=str(d.get('id',''))
 try:rating=int(d.get('rating'))
 except:return err('Calificación inválida')
 if not 1<=rating<=5 or not 15<=len(body)<=1200 or typ not in ('artist','venue','event'):return err('Revisa tu reseña (15 a 1200 caracteres).')
 with conn() as c:c.execute('INSERT INTO reviews(user_id,entity_type,entity_id,rating,body) VALUES(?,?,?,?,?)',(session['uid'],typ,eid,rating,body))
 return jsonify(ok=True,message='Reseña recibida. Se publicará tras moderación.')

@app.post('/api/collaborations')
@auth
@limiter.limit('12 per day')
def collaboration():
 d=data();msg=str(d.get('message','')).strip();typ=d.get('type');eid=str(d.get('id',''));u=current_user()
 if not u['membership'] or u['membership']['status']!='active':return err('Necesitas una membresía activa.',403)
 if not 20<=len(msg)<=3000 or (u['role'],typ) not in [('artist','venue'),('venue','artist')]:return err('Se requiere una cuenta profesional del tipo correspondiente y una propuesta de 20 a 3000 caracteres.')
 with conn() as c:
  target=c.execute("SELECT claims.user_id FROM claims JOIN users ON users.id=claims.user_id WHERE entity_type=? AND entity_id=? AND status='approved' AND users.role=?",(typ,eid,typ)).fetchone()
  if not target:return err('Este perfil aún no tiene titular verificado. Utiliza sus canales públicos de contacto.',409)
  if target[0]==u['id']:return err('No puedes enviarte una propuesta.')
  cur=c.execute('INSERT INTO collaborations(user_id,entity_type,entity_id,message) VALUES(?,?,?,?)',(u['id'],typ,eid,msg))
  c.execute('INSERT INTO threads(id,sender,recipient) VALUES(?,?,?)',(cur.lastrowid,u['id'],target[0]))
  c.execute('INSERT INTO messages(thread_id,sender,body) VALUES(?,?,?)',(cur.lastrowid,u['id'],msg))
 return jsonify(ok=True,message='Propuesta enviada al titular del perfil.')

with conn() as c:
 c.executescript("""CREATE TABLE IF NOT EXISTS threads(id INTEGER PRIMARY KEY REFERENCES collaborations(id),sender INTEGER NOT NULL REFERENCES users(id),recipient INTEGER NOT NULL REFERENCES users(id),status TEXT DEFAULT 'Enviada');CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,thread_id INTEGER REFERENCES threads(id),sender INTEGER REFERENCES users(id),body TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS review_reports(id INTEGER PRIMARY KEY,review_id INTEGER REFERENCES reviews(id),user_id INTEGER REFERENCES users(id),reason TEXT,UNIQUE(review_id,user_id));""")

@app.get('/api/inbox')
@auth
def inbox():
 uid=session['uid']
 with conn() as c:
  rows=[dict(r) for r in c.execute('SELECT threads.*,users.name AS contact FROM threads JOIN users ON users.id=CASE WHEN sender=? THEN recipient ELSE sender END WHERE sender=? OR recipient=? ORDER BY threads.id DESC',(uid,uid,uid))]
  for r in rows:r['messages']=[dict(m) for m in c.execute('SELECT * FROM messages WHERE thread_id=? ORDER BY id',(r['id'],))]
 return jsonify(threads=rows)

@app.post('/api/inbox/reply')
@auth
@limiter.limit('60 per hour')
def reply():
 d=data();uid=session['uid'];body=str(d.get('body','')).strip();status=d.get('status')
 with conn() as c:
  t=c.execute('SELECT * FROM threads WHERE id=? AND (sender=? OR recipient=?)',(d.get('id'),uid,uid)).fetchone()
  if not t:return err('Conversación no disponible',404)
  if not 1<=len(body)<=3000:return err('Escribe un mensaje válido.')
  if status and status not in ['En revisión','En negociación','Aceptada','Evento confirmado','Finalizada','Rechazada','Cancelada']:return err('Estado inválido')
  if status and status in ['Aceptada','Rechazada'] and uid!=t['recipient']:return err('Solo el destinatario puede aceptar o rechazar.',403)
  c.execute('INSERT INTO messages(thread_id,sender,body) VALUES(?,?,?)',(t['id'],uid,body))
  if status:c.execute('UPDATE threads SET status=? WHERE id=?',(status,t['id']))
 return jsonify(ok=True,message='Mensaje enviado.')

@app.post('/api/reviews/manage')
@auth
def manage_review():
 d=data();uid=session['uid'];rid=d.get('id');action=d.get('action')
 with conn() as c:
  r=c.execute('SELECT * FROM reviews WHERE id=?',(rid,)).fetchone()
  if not r:return err('Comentario no encontrado',404)
  if action=='report':
   reason=str(d.get('reason','')).strip()
   if not reason or len(reason)>500:return err('Indica el motivo del reporte.')
   c.execute('INSERT OR IGNORE INTO review_reports(review_id,user_id,reason) VALUES(?,?,?)',(rid,uid,reason));c.execute("UPDATE reviews SET status='pending' WHERE id=?",(rid,))
  elif r['user_id']!=uid:return err('No autorizado',403)
  elif action=='delete':c.execute('DELETE FROM review_reports WHERE review_id=?',(rid,));c.execute('DELETE FROM reviews WHERE id=?',(rid,))
  elif action=='edit':
   body=str(d.get('body','')).strip()
   if not 15<=len(body)<=1200:return err('Escribe entre 15 y 1200 caracteres.')
   c.execute("UPDATE reviews SET body=?,status='pending' WHERE id=?",(body,rid))
  else:return err('Acción inválida')
 return jsonify(ok=True,message='Comentario actualizado.')

@app.post('/api/claims')
@auth
def claim():
 d=data();evidence=str(d.get('evidence','')).strip()
 if d.get('type') not in ('artist','venue') or len(evidence)<20:return err('Describe cómo verificaremos que eres titular del perfil.')
 with conn() as c:c.execute('INSERT INTO claims(user_id,entity_type,entity_id,evidence) VALUES(?,?,?,?)',(session['uid'],d['type'],str(d.get('id','')),evidence[:2000]))
 return jsonify(ok=True,message='Solicitud de titularidad recibida; pendiente de revisión.')

@app.post('/api/events')
@auth
def submit_event():
 u=current_user();d=data()
 if u['role'] not in ('artist','venue'):return err('Solo artistas y espacios pueden proponer eventos.',403)
 if not u['membership'] or u['membership']['status'] not in ('active','trialing'):return err('Para publicar eventos necesitas una membresía activa.',403)
 name=str(d.get('name','')).strip();desc=str(d.get('description','')).strip()
 if len(name)<5 or len(desc)<20 or not d.get('starts_at'):return err('Completa nombre, fecha y descripción.')
 eid='community-'+secrets.token_hex(8)
 with conn() as c:c.execute('INSERT INTO events(id,name,category,starts_at,location_name,address,description,price,status,submitted_by,approved) VALUES(?,?,?,?,?,?,?,?,?,?,0)',(eid,name[:140],str(d.get('category','Cultura'))[:50],d['starts_at'],str(d.get('location_name',''))[:150],str(d.get('address',''))[:250],desc[:3000],str(d.get('price','Por confirmar'))[:80],'En revisión',u['id']))
 return jsonify(ok=True,message='Evento enviado a revisión editorial.')

@app.post('/api/billing/checkout')
@auth
@limiter.limit('10 per hour')
def checkout():
 d=data();plan=d.get('plan');period=d.get('period','monthly');u=current_user()
 if plan not in PLANS or period not in ('monthly','semiannual','annual'):return err('Plan inválido')
 if u['role']!=PLANS[plan]['role']:return err('El plan no corresponde a tu tipo de cuenta.')
 key=os.environ.get('STRIPE_SECRET_KEY');price=os.environ.get('STRIPE_PRICE_'+plan.upper()+'_'+period.upper())
 if not key or not price:return err('Cobros aún no habilitados: faltan credenciales y precios de Stripe.',503)
 try:
  import stripe
  stripe.api_key=key
  origin=os.environ.get('PUBLIC_BASE_URL','').rstrip('/')
  if not origin.startswith('https://'):return err('Configura PUBLIC_BASE_URL con HTTPS para habilitar cobros.',503)
  checkout=stripe.checkout.Session.create(mode='subscription',line_items=[{'price':price,'quantity':1}],client_reference_id=str(u['id']),customer_email=u['email'],success_url=origin+'/?payment=success',cancel_url=origin+'/?payment=cancel',metadata={'user_id':str(u['id']),'plan':plan,'period':period},subscription_data={'metadata':{'user_id':str(u['id']),'plan':plan,'period':period}})
  return jsonify(url=checkout.url)
 except Exception:app.logger.exception('stripe checkout');return err('No fue posible iniciar el pago. Intenta más tarde.',502)

@app.post('/api/billing/portal')
@auth
def portal():
 key=os.environ.get('STRIPE_SECRET_KEY');u=current_user()
 with conn() as c:s=c.execute('SELECT stripe_customer_id FROM subscriptions WHERE user_id=?',(u['id'],)).fetchone()
 if not key or not s or not s['stripe_customer_id']:return err('No existe una suscripción de pago administrable.',404)
 try:
  import stripe
  stripe.api_key=key
  p=stripe.billing_portal.Session.create(customer=s['stripe_customer_id'],return_url=os.environ['PUBLIC_BASE_URL'].rstrip('/')+'/')
  return jsonify(url=p.url)
 except Exception:app.logger.exception('stripe portal');return err('No fue posible abrir el portal de pagos.',502)

@app.post('/api/stripe/webhook')
def webhook():
 key=os.environ.get('STRIPE_SECRET_KEY');secret=os.environ.get('STRIPE_WEBHOOK_SECRET')
 if not key or not secret:return err('Webhook no configurado',503)
 try:
  import stripe
  stripe.api_key=key
  ev=stripe.Webhook.construct_event(request.data,request.headers.get('Stripe-Signature',''),secret)
 except Exception:return err('Firma inválida',400)
 with conn() as c:
  if c.execute('SELECT 1 FROM webhook_events WHERE event_id=?',(ev['id'],)).fetchone():return jsonify(ok=True)
  obj=ev['data']['object'];typ=ev['type']
  if typ=='checkout.session.completed' and obj.get('mode')=='subscription':
   uid=obj.get('client_reference_id');plan=(obj.get('metadata') or {}).get('plan')
   if uid and plan in PLANS:
    c.execute('INSERT INTO subscriptions(user_id,plan,status,stripe_customer_id,stripe_subscription_id) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan,stripe_customer_id=excluded.stripe_customer_id,stripe_subscription_id=excluded.stripe_subscription_id,updated_at=CURRENT_TIMESTAMP',(uid,plan+':'+(obj.get('metadata') or {}).get('period','monthly'),'pending',obj.get('customer'),obj.get('subscription')))
  elif typ in ('customer.subscription.created','customer.subscription.updated','customer.subscription.deleted'):
   subid=obj.get('id');status=obj.get('status','inactive');uid=(obj.get('metadata') or {}).get('user_id');plan=(obj.get('metadata') or {}).get('plan')
   if uid and plan in PLANS:
    c.execute('INSERT INTO subscriptions(user_id,plan,status,stripe_customer_id,stripe_subscription_id) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan,status=excluded.status,stripe_customer_id=excluded.stripe_customer_id,stripe_subscription_id=excluded.stripe_subscription_id,updated_at=CURRENT_TIMESTAMP',(uid,plan+':'+(obj.get('metadata') or {}).get('period','monthly'),status,obj.get('customer'),subid))
   else:c.execute('UPDATE subscriptions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?',(status,subid))
  c.execute('INSERT INTO webhook_events(event_id) VALUES(?)',(ev['id'],))
 return jsonify(ok=True)

@app.get('/api/health')
def health():return jsonify(status='ok',service='ATELIER')

# Administración: requiere cuenta con correo explícitamente autorizado en ADMIN_EMAIL.
def is_admin():
 u=current_user();return bool(u and os.environ.get('ADMIN_EMAIL') and u['email']==os.environ['ADMIN_EMAIL'].strip().lower())
@app.get('/api/admin/queue')
@auth
def admin_queue():
 if not is_admin():return err('Acceso restringido',403)
 with conn() as c:
  return jsonify(reviews=[dict(x) for x in c.execute("SELECT reviews.*,users.name FROM reviews JOIN users ON users.id=reviews.user_id WHERE reviews.status='pending'")],claims=[dict(x) for x in c.execute("SELECT * FROM claims WHERE status='pending'")],events=[dict(x) for x in c.execute('SELECT * FROM events WHERE approved=0')],collaborations=[dict(x) for x in c.execute("SELECT * FROM collaborations WHERE status='new'")])
@app.post('/api/admin/moderate')
@auth
def admin_moderate():
 if not is_admin():return err('Acceso restringido',403)
 d=data();typ=d.get('type');ident=d.get('id');decision=d.get('decision')
 tables={'review':('reviews','status'),'claim':('claims','status'),'event':('events','approved'),'collaboration':('collaborations','status')}
 if typ not in tables or decision not in ('approve','reject'):return err('Acción inválida')
 table,col=tables[typ];value=(1 if decision=='approve' else -1) if typ=='event' else ('approved' if decision=='approve' else 'rejected') if typ in ('review','claim') else ('reviewed' if decision=='approve' else 'rejected')
 with conn() as c:
  r=c.execute(f'UPDATE {table} SET {col}=? WHERE id=?',(value,ident))
  if r.rowcount!=1:return err('Registro no encontrado',404)
 return jsonify(ok=True)

if __name__=='__main__':app.run(host='127.0.0.1',port=int(os.environ.get('PORT','5000')),debug=False)
