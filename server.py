import os, sqlite3, secrets, smtplib, ssl, json, datetime, io, hmac
from pathlib import Path
from email.message import EmailMessage
from flask import Flask, request, jsonify, send_from_directory, session, redirect, render_template_string
from werkzeug.utils import secure_filename
from zoneinfo import ZoneInfo

BASE=Path(__file__).resolve().parent
DATA=Path(os.getenv('DATA_DIR',str(BASE/'private_data'))); DATA.mkdir(parents=True,exist_ok=True)
UPLOAD=DATA/'slips'; UPLOAD.mkdir(exist_ok=True)
app=Flask(__name__,static_folder=None)
app.secret_key=os.environ.get('SESSION_SECRET',secrets.token_hex(32))
app.config.update(MAX_CONTENT_LENGTH=10*1024*1024+1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','1')=='1')
PRICES={'Q':550,'T':650,'D':300}; COUNTS={'Q':2,'T':3,'D':4}
DB=DATA/'bookings.sqlite3'
def conn():
 c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; return c
with conn() as c:
 c.execute('CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY,code TEXT UNIQUE NOT NULL,guest TEXT NOT NULL,phone TEXT NOT NULL,email TEXT NOT NULL,ci TEXT NOT NULL,co TEXT NOT NULL,items TEXT NOT NULL,total INTEGER NOT NULL,notes TEXT,slip TEXT NOT NULL,status TEXT NOT NULL DEFAULT "pending",created TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS inventory(room TEXT NOT NULL,day TEXT NOT NULL,closed INTEGER NOT NULL DEFAULT 0,price INTEGER,PRIMARY KEY(room,day))')

def send_mail(to,subject,body,slip=None,cc=None):
 host=os.getenv('SMTP_HOST'); user=os.getenv('SMTP_USER'); password=os.getenv('SMTP_PASSWORD'); sender=os.getenv('SMTP_FROM',user)
 if not all([host,user,password,sender]): raise RuntimeError('ยังไม่ได้ตั้งค่า SMTP')
 msg=EmailMessage(); msg['From']=sender; msg['To']=to; msg['Subject']=subject
 if cc:msg['Cc']=cc
 msg.set_content(body)
 if slip:
  from mimetypes import guess_type
  typ=(guess_type(str(slip))[0] or 'application/octet-stream').split('/')
  msg.add_attachment(Path(slip).read_bytes(),maintype=typ[0],subtype=typ[1],filename=Path(slip).name)
 with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=25) as s:
  s.starttls(context=ssl.create_default_context());s.login(user,password);s.send_message(msg)

def fmt(x):return datetime.date.fromisoformat(x).strftime('%d/%m/%Y')
def details(r):
 items=json.loads(r['items']); nights=(datetime.date.fromisoformat(r['co'])-datetime.date.fromisoformat(r['ci'])).days
 return '\n'.join([f'รหัสการจอง: {r["code"]}',f'ชื่อ: {r["guest"]}',f'เบอร์โทร: {r["phone"]}',f'อีเมล: {r["email"]}',f'เช็กอิน: {fmt(r["ci"])}',f'เช็กเอาต์: {fmt(r["co"])}',f'จำนวนคืน: {nights}',*([f'{i["type"]}: {i["qty"]} ห้อง/เตียง' for i in items]),f'ยอดชำระ 100%: {r["total"]:,} บาท',f'หมายเหตุ: {r["notes"] or "-"}','เงื่อนไข: ไม่คืนเงิน สามารถขอเปลี่ยนวันตามห้องว่างและราคาใหม่ได้'])
@app.get('/')
def home():return send_from_directory(BASE,'customer.html')
@app.get('/admin')
def admin():return send_from_directory(BASE,'admin.html')
@app.get('/api/availability')
def availability():
 ci=request.args.get('ci');co=request.args.get('co')
 try:
  start=datetime.date.fromisoformat(ci);end=datetime.date.fromisoformat(co);n=(end-start).days
  if not 1<=n<=7:raise ValueError()
 except: return jsonify(error='วันที่ไม่ถูกต้อง'),400
 with conn() as c:
  result={}
  for typ,count in COUNTS.items():
   available=[]
   for ix in range(1,count+1):
    room=f'{typ}{ix}'; good=True
    for k in range(n):
     day=(start+datetime.timedelta(days=k)).isoformat()
     if c.execute('SELECT closed FROM inventory WHERE room=? AND day=?',(room,day)).fetchone() and c.execute('SELECT closed FROM inventory WHERE room=? AND day=?',(room,day)).fetchone()['closed']:good=False;break
     rows=c.execute('SELECT items FROM bookings WHERE status IN ("pending","confirmed") AND ci<? AND co>?',(co,ci)).fetchall()
     # conservative type-count availability: check max overlap below separately
    if good:available.append(room)
   # pending/confirmed allocations are tracked by room codes in items
   reserved=set()
   for r in c.execute('SELECT items FROM bookings WHERE status IN ("pending","confirmed") AND ci<? AND co>?',(co,ci)):
    for item in json.loads(r['items']):reserved.update(item.get('rooms',[]))
   result[typ]={'available':len([x for x in available if x not in reserved]),'price':PRICES[typ]}
 return jsonify(result)
@app.post('/api/book')
def book():
 now=datetime.datetime.now(ZoneInfo('Asia/Bangkok'))
 if not (8<=now.hour<17):return jsonify(error='รับคำขอจองเวลา 08:00–17:00 น. เวลาไทย'),400
 guest=request.form.get('guest','').strip();phone=request.form.get('phone','').strip();email=request.form.get('email','').strip();notes=request.form.get('notes','').strip()[:1000]
 try:
  ci=datetime.date.fromisoformat(request.form['ci']);co=datetime.date.fromisoformat(request.form['co']);n=(co-ci).days
  qty={t:int(request.form.get(t,0)) for t in COUNTS}
  if not (datetime.date(2026,10,1)<=ci<co<=datetime.date(2027,10,28) and 1<=n<=7):raise ValueError()
  if not any(qty.values()) or any(not 0<=qty[t]<=COUNTS[t] for t in COUNTS):raise ValueError()
  if not guest or len(phone)<9 or '@' not in email:raise ValueError()
 except:return jsonify(error='ข้อมูลการจองไม่ถูกต้อง'),400
 f=request.files.get('slip')
 if not f:return jsonify(error='กรุณาแนบสลิป'),400
 data=f.read(10*1024*1024+1)
 if len(data)>10*1024*1024:return jsonify(error='ไฟล์ใหญ่เกิน 10 MB'),400
 from PIL import Image
 kind=None
 if data.startswith(b'%PDF-'):kind='pdf'
 else:
  try:
   im=Image.open(io.BytesIO(data));im.verify();kind={'JPEG':'jpg','PNG':'png'}.get(im.format)
  except:pass
 if kind is None:return jsonify(error='รองรับเฉพาะ JPG PNG PDF'),400
 with conn() as c:
  c.execute('BEGIN IMMEDIATE')
  items=[];total=0
  for typ,q in qty.items():
   if not q:continue
   free=[]
   for idx in range(1,COUNTS[typ]+1):
    room=f'{typ}{idx}';blocked=False
    for d in range(n):
     day=(ci+datetime.timedelta(days=d)).isoformat()
     row=c.execute('SELECT closed FROM inventory WHERE room=? AND day=?',(room,day)).fetchone()
     if row and row['closed']:blocked=True;break
    if blocked:continue
    for r in c.execute('SELECT items FROM bookings WHERE status IN ("pending","confirmed") AND ci<? AND co>?',(co.isoformat(),ci.isoformat())):
     if any(room in i.get('rooms',[]) for i in json.loads(r['items'])):blocked=True;break
    if not blocked:free.append(room)
   if len(free)<q:return jsonify(error=f'ห้องประเภท {typ} ไม่พอ กรุณาเลือกใหม่'),409
   selected=free[:q];items.append({'type':typ,'qty':q,'rooms':selected});total+=q*PRICES[typ]*n
  for _ in range(100):
   code=f'{secrets.randbelow(10000):04d}'
   if not c.execute('SELECT 1 FROM bookings WHERE code=?',(code,)).fetchone():break
  else:return jsonify(error='รหัสจองเต็ม กรุณาติดต่อโรงแรม'),503
  slipname=f'{secrets.token_hex(16)}.{kind}';(UPLOAD/slipname).write_bytes(data)
  c.execute('INSERT INTO bookings(code,guest,phone,email,ci,co,items,total,notes,slip,status,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(code,guest,phone,email,ci.isoformat(),co.isoformat(),json.dumps(items),total,notes,slipname,'pending',now.isoformat()))
  r=c.execute('SELECT * FROM bookings WHERE code=?',(code,)).fetchone()
 text=details(r)
 try:
  send_mail('paipaihostel@gmail.com',f'คำขอจองใหม่ #{code}',text+'\n\nสถานะ: รอตรวจสอบสลิป',UPLOAD/slipname,cc='kornthaifood@gmail.com')
  send_mail(email,f'PaiPai Hostel รับคำขอจอง #{code}',text+'\n\nเราได้รับคำขอแล้ว แต่ยังไม่ยืนยันห้องพัก โปรดรออีเมลยืนยันจากโรงแรม')
 except Exception as e:
  app.logger.exception('email failed for booking %s',code)
  return jsonify(code=code,total=total,status='pending',email_sent=False,message='บันทึกคำขอแล้ว แต่ส่งอีเมลไม่สำเร็จ โปรดติดต่อโรงแรมพร้อมรหัสจอง'),202
 return jsonify(code=code,total=total,status='pending',email_sent=True)

def authed():return bool(session.get('admin'))
@app.post('/api/admin/login')
def login():
 expected=os.getenv('ADMIN_PASSWORD')
 if not expected:return jsonify(error='ผู้ดูแลยังไม่ได้ตั้งรหัสผ่านบนเซิร์ฟเวอร์'),503
 if not hmac.compare_digest(request.get_json(silent=True).get('password','') if request.is_json else '',expected):return jsonify(error='รหัสผ่านไม่ถูกต้อง'),401
 session['admin']=True;return jsonify(ok=True)
@app.post('/api/admin/logout')
def logout():session.clear();return jsonify(ok=True)
@app.get('/api/admin/bookings')
def bookings():
 if not authed():return jsonify(error='กรุณาเข้าสู่ระบบ'),401
 with conn() as c:rows=[dict(r) for r in c.execute('SELECT * FROM bookings ORDER BY id DESC LIMIT 500')]
 for r in rows:r.pop('slip',None)
 return jsonify(rows)
@app.get('/api/admin/slip/<code>')
def slip(code):
 if not authed():return 'Unauthorized',401
 with conn() as c:r=c.execute('SELECT slip FROM bookings WHERE code=?',(code,)).fetchone()
 if not r:return 'Not found',404
 return send_from_directory(UPLOAD,r['slip'])
@app.post('/api/admin/status/<code>')
def status(code):
 if not authed():return jsonify(error='กรุณาเข้าสู่ระบบ'),401
 new=(request.get_json(silent=True) or {}).get('status')
 if new not in ('confirmed','cancelled'):return jsonify(error='สถานะไม่ถูกต้อง'),400
 with conn() as c:
  r=c.execute('SELECT * FROM bookings WHERE code=?',(code,)).fetchone()
  if not r:return jsonify(error='ไม่พบการจอง'),404
  c.execute('UPDATE bookings SET status=? WHERE code=?',(new,code))
 try:
  subject=('ยืนยันการจอง' if new=='confirmed' else 'แจ้งยกเลิกการจอง')+f' PaiPai Hostel #{code}'
  send_mail(r['email'],subject,details(r)+'\n\nสถานะ: '+('ยืนยันการจองแล้ว' if new=='confirmed' else 'ยกเลิกการจองแล้ว'))
  return jsonify(ok=True,email_sent=True)
 except Exception:
  app.logger.exception('status email failed %s',code)
  return jsonify(ok=True,email_sent=False,message='เปลี่ยนสถานะแล้ว แต่ส่งอีเมลไม่สำเร็จ'),202
@app.post('/api/admin/inventory')
def inventory():
 if not authed():return jsonify(error='กรุณาเข้าสู่ระบบ'),401
 data=request.get_json(silent=True) or {};room=data.get('room');day=data.get('day')
 try:datetime.date.fromisoformat(day);price=int(data.get('price',0));assert room in [f'{t}{i}' for t,n in COUNTS.items() for i in range(1,n+1)] and price>0
 except:return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
 with conn() as c:c.execute('INSERT INTO inventory(room,day,closed,price) VALUES(?,?,?,?) ON CONFLICT(room,day) DO UPDATE SET closed=excluded.closed,price=excluded.price',(room,day,int(bool(data.get('closed'))),price))
 return jsonify(ok=True)
@app.get('/api/admin/inventory')
def get_inventory():
 if not authed():return jsonify(error='กรุณาเข้าสู่ระบบ'),401
 with conn() as c:return jsonify([dict(r) for r in c.execute('SELECT * FROM inventory')])
if __name__=='__main__':app.run(debug=False,port=int(os.getenv('PORT','5000')))
