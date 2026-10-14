from pathlib import Path
p=Path(__file__).parent
s=Path('/mnt/data/paipai_booking_full_payment.html').read_text()
start=s.index("$('send').addEventListener('click'")
end=s.index('function bangkokMinutes()',start)
replacement='''$('send').addEventListener('click',async()=>{
 if(!isOfficeOpen()){alert('เปิดรับคำขอจอง 08:00–17:00 น.');return;}
 const f=$('slip').files[0];if(!f||!body){alert('กรุณาสร้างใบสรุปและแนบสลิปก่อน');return;}
 const fd=new FormData();for(const [key,val] of Object.entries({guest:$('guest').value,phone:$('phone').value,email:$('email').value,ci:$('ci').value,co:$('co').value,notes:$('note').value,Q:qty.Q,T:qty.T,D:qty.D}))fd.append(key,val);fd.append('slip',f);
 $('send').disabled=true;$('send').textContent='กำลังบันทึกและส่งอีเมล…';
 try{const res=await fetch('/api/book',{method:'POST',body:fd});const data=await res.json();if(!res.ok){alert(data.error||'ส่งไม่สำเร็จ');return;}
 $('requestStatus').innerHTML='<b>เลขจอง '+esc(data.code)+'</b><p>'+ (data.email_sent?'บันทึกคำขอและส่งอีเมลให้ลูกค้าและโรงแรมแล้ว กรุณารอการยืนยัน':'บันทึกคำขอแล้ว แต่ส่งอีเมลไม่สำเร็จ โปรดติดต่อโรงแรมพร้อมรหัสจอง')+'</p>';
 $('receipt').insertAdjacentHTML('afterbegin','<h2>รหัสการจอง: '+esc(data.code)+'</h2>');$('receiptSection').scrollIntoView({behavior:'smooth'});$('send').style.display='none';
 }catch(e){alert('เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ กรุณาลองใหม่');}finally{$('send').disabled=false;$('send').textContent='ส่งคำขอจองและสลิปทางอีเมล';}
});'''
s=s[:start]+replacement+s[end:]
s=s.replace('ต้องกดส่งอีเมลด้วยตนเอง และรอ','ระบบจะส่งอีเมลหลังส่งคำขอสำเร็จ และรอ').replace('ต้องแนบไฟล์ด้วยตนเองในแอปอีเมล','ระบบแนบไฟล์ไปพร้อมคำขอโดยอัตโนมัติ')
s=s.replace('ส่งอีเมลคำขอจอง','ส่งคำขอจองและสลิปทางอีเมล')
(p/'customer.html').write_text(s)
