
(function(){
 const $=id=>document.getElementById(id);
 const add=(parent,html)=>parent.insertAdjacentHTML("beforeend",html);
 const exam=$("page-exams");
 add(exam,'<div class="card panel" style="margin-top:16px"><h2>بانک درس‌ها و مباحث</h2><p>درس‌ها و مباحث را ذخیره کنید تا در آزمون‌های بعدی نیز قابل استفاده باشند.</p><form id="subjectForm" class="toolbar"><input name="name" placeholder="نام درس جدید" required><button class="btn btn-primary">افزودن درس</button></form><div id="subjectList"></div><button class="btn btn-outline" id="refreshSubjects" type="button">به‌روزرسانی فهرست</button></div>');
 add(exam,'<div class="card panel" style="margin-top:16px"><h2>تقسیم‌بندی درس و مبحث آزمون</h2><p>برای هر بخش، شماره شروع و تعداد سؤال را مشخص کنید.</p><select id="sectionExam" class="section-control"><option value="">انتخاب آزمون</option></select><div id="sectionList"></div><button class="btn btn-outline" id="addSection" type="button">افزودن بخش</button><button class="btn btn-primary" id="saveSections" type="button">ذخیره تقسیم‌بندی</button></div>');
 const form=$("examForm");
 add(form,'<div class="card manual-key" style="padding:12px;margin:12px 0"><b>ورود دستی کلید پاسخ</b><button type="button" class="btn btn-outline" id="manualKeyBuild">ساخت جدول گزینه‌ها</button><div id="manualKeyGrid" class="manual-key-grid"></div></div>');
 const style=document.createElement("style");style.textContent='.manual-key-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;max-height:340px;overflow:auto;margin-top:10px}.manual-row{display:flex;align-items:center;gap:7px;border:1px solid #e7ebf1;border-radius:8px;padding:6px}.manual-row button{width:25px;height:25px;border-radius:50%;border:1px solid #ccd3df;background:#fff}.manual-row button.on{background:#17243a;color:white}.section-control,.section-row select,.section-row input{padding:8px;border:1px solid #dfe4ec;border-radius:8px}.section-row{display:grid;grid-template-columns:1fr 1fr .6fr .6fr auto;gap:7px;margin:8px 0}.subject-card{border:1px solid #e7ebf1;border-radius:10px;padding:10px;margin:8px 0}.subject-card button{margin:3px}.lesson-row{padding:6px 12px;border-bottom:1px solid #edf0f4;font-size:11px}@media(max-width:700px){.manual-key-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.section-row{grid-template-columns:1fr 1fr}}';
 document.head.appendChild(style);
 function api(){return window.dadyarWorkspace||{}}
 async function loadCatalog(){
  const {sb,profile}=api();if(!sb||!profile)return;
  const [a,b]=await Promise.all([sb.from("subjects").select("*").order("sort_order"),sb.from("lessons").select("*").order("sort_order")]);
  if(a.error||b.error){window.alert((a.error||b.error).message);return}
  const subjects=a.data||[],lessons=b.data||[];window.dadyarCatalog={subjects,lessons};
  $("subjectList").innerHTML=subjects.map((s,i)=>'<div class="subject-card"><b>'+s.name+'</b><button class="btn btn-light" data-edit-sub="'+s.id+'">ویرایش</button><button class="btn btn-danger" data-del-sub="'+s.id+'">حذف</button><button class="btn btn-light" data-up-sub="'+s.id+'">↑</button><button class="btn btn-light" data-down-sub="'+s.id+'">↓</button><div>'+lessons.filter(l=>l.subject_id===s.id).map(l=>'<div class="lesson-row">'+l.name+' <button class="btn btn-light" data-edit-les="'+l.id+'">ویرایش</button><button class="btn btn-danger" data-del-les="'+l.id+'">حذف</button></div>').join("")+'</div><form data-add-les="'+s.id+'" class="toolbar"><input name="name" placeholder="مبحث جدید" required><button class="btn btn-outline">افزودن مبحث</button></form></div>').join("")||'<div class="empty">درسی ثبت نشده است.</div>';
  $("subjectList").querySelectorAll("[data-edit-sub]").forEach(b=>b.onclick=async()=>{const s=subjects.find(x=>x.id===b.dataset.editSub),v=prompt("نام درس",s.name);if(v?.trim()){await sb.from("subjects").update({name:v.trim()}).eq("id",s.id);loadCatalog()}});
  $("subjectList").querySelectorAll("[data-del-sub]").forEach(b=>b.onclick=async()=>{if(confirm("درس حذف شود؟")){const r=await sb.from("subjects").delete().eq("id",b.dataset.delSub);if(r.error)alert(r.error.message);loadCatalog()}});
  $("subjectList").querySelectorAll("[data-edit-les]").forEach(b=>b.onclick=async()=>{const l=lessons.find(x=>x.id===b.dataset.editLes),v=prompt("نام مبحث",l.name);if(v?.trim()){await sb.from("lessons").update({name:v.trim()}).eq("id",l.id);loadCatalog()}});
  $("subjectList").querySelectorAll("[data-del-les]").forEach(b=>b.onclick=async()=>{await sb.from("lessons").delete().eq("id",b.dataset.delLes);loadCatalog()});
  $("subjectList").querySelectorAll("form[data-add-les]").forEach(f=>f.onsubmit=async e=>{e.preventDefault();const r=await sb.from("lessons").insert({institution_id:profile.institution_id,subject_id:f.dataset.addLes,name:f.querySelector('input').value.trim(),sort_order:lessons.filter(x=>x.subject_id===f.dataset.addLes).length});if(r.error)alert(r.error.message);loadCatalog()});
  const sel=$("sectionExam"),old=sel.value;sel.innerHTML='<option value="">انتخاب آزمون</option>'+((window.dadyarWorkspace?.exams)||[]).map(e=>'<option value="'+e.id+'">'+e.title+'</option>').join("");sel.value=old;
 }
 $("subjectForm").onsubmit=async e=>{e.preventDefault();const {sb,profile}=api();if(!sb||!profile)return;const {error}=await sb.from("subjects").insert({institution_id:profile.institution_id,name:e.target.querySelector('input').value.trim(),sort_order:$("subjectList").children.length});if(error)alert(error.message);else{e.target.reset();loadCatalog()}};
 $("refreshSubjects").onclick=loadCatalog;
 $("manualKeyBuild").onclick=()=>{
  const n=Math.max(1,Math.min(300,Number($("examCount").value)||1)),a=$("answerKey").value.split(/[,،\s]+/).filter(Boolean);
  $("manualKeyGrid").innerHTML=Array.from({length:n},(_,i)=>'<div class="manual-row" data-q="'+i+'"><b>'+String(i+1)+'</b>'+[1,2,3,4].map(k=>'<button type="button" data-v="'+k+'" class="'+(String(k)===String(a[i])?'on':'')+'">'+k+'</button>').join("")+'</div>').join("");
  $("manualKeyGrid").querySelectorAll("button[data-v]").forEach(b=>b.onclick=()=>{b.parentElement.querySelectorAll("button").forEach(x=>x.classList.remove("on"));b.classList.add("on");$("answerKey").value=Array.from($("manualKeyGrid").querySelectorAll(".manual-row"),r=>r.querySelector(".on")?.dataset.v||"").join(",")});
 };
 $("addSection").onclick=()=>{
  const {subjects,lessons}=window.dadyarCatalog||{subjects:[],lessons:[]};
  const opts=subjects.map(s=>'<option value="'+s.id+'">'+s.name+'</option>').join("");
  $("sectionList").insertAdjacentHTML("beforeend",'<div class="section-row"><select class="sub"><option value="">درس</option>'+opts+'</select><select class="les"><option value="">همه مباحث</option></select><input class="start" type="number" min="1" placeholder="شروع" value="1"><input class="count" type="number" min="1" placeholder="تعداد" value="10"><button type="button" class="btn btn-danger">×</button></div>');
  const row=$("sectionList").lastElementChild;row.querySelector(".sub").onchange=()=>{const ls=lessons.filter(l=>l.subject_id===row.querySelector(".sub").value);row.querySelector(".les").innerHTML='<option value="">همه مباحث</option>'+ls.map(l=>'<option value="'+l.id+'">'+l.name+'</option>').join("")};row.querySelector("button").onclick=()=>row.remove();
 };
 $("saveSections").onclick=async()=>{
  const {sb,profile,exams}=api(),examId=$("sectionExam").value;if(!examId){alert("آزمون را انتخاب کنید.");return}
  const rows=Array.from($("sectionList").querySelectorAll(".section-row"));
  const data=rows.map((r,i)=>({institution_id:profile.institution_id,exam_id:examId,subject_id:r.querySelector(".sub").value,lesson_id:r.querySelector(".les").value||null,question_start:Number(r.querySelector(".start").value),question_count:Number(r.querySelector(".count").value),sort_order:i}));
  const sorted=data.slice().sort((a,b)=>a.question_start-b.question_start);
  if(data.some(x=>!x.subject_id||x.question_start<1||x.question_count<1)||sorted.some((x,i)=>i&&x.question_start<sorted[i-1].question_start+sorted[i-1].question_count)){alert("بخش‌ها ناقص هستند یا بازه سؤال‌ها هم‌پوشانی دارد.");return}
  await sb.from("exam_sections").delete().eq("exam_id",examId);
  const r=data.length?await sb.from("exam_sections").insert(data):{error:null};if(r.error)alert(r.error.message);else alert("تقسیم‌بندی ذخیره شد.");
 };
 const wait=setInterval(()=>{const {sb,profile}=api();if(sb&&profile){clearInterval(wait);loadCatalog()}},600);
})();
