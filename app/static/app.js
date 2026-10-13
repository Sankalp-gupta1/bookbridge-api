const state={page:1,category:null,search:null,bookPage:null,currentBooks:{}};
const $=s=>document.querySelector(s);
const grid=$("#bookGrid"),notice=$("#notice"),resultLabel=$("#resultLabel"),sourceLabel=$("#sourceLabel");
const escapeHtml=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
function showNotice(message){notice.textContent=message;notice.classList.remove("hidden")}
function clearNotice(){notice.classList.add("hidden")}
function money(p){return p?escapeHtml(p.currency)+" "+escapeHtml(p.amount):"—"}
function stars(n){n=Number(n)||0;return "★".repeat(n)+"☆".repeat(Math.max(0,5-n))}
function renderBooks(items){
  items=items||[];
  state.currentBooks=Object.fromEntries(items.map(book=>[book.id,book]));
  if(!items.length){grid.innerHTML='<div class="empty">No books found in this demo slice.</div>';return}
  grid.innerHTML=items.map((b,i)=>'<article class="book-card"><span class="book-index">BOOK '+String(i+1).padStart(2,"0")+'</span><h3>'+escapeHtml(b.title)+'</h3><div class="card-spacer"></div><div class="price-row"><div><div class="price">'+money(b.price)+'</div><div class="stock">'+(b.in_stock?"In stock":"Out of stock")+'</div></div><div class="rating" title="'+escapeHtml(b.rating)+' stars">'+stars(b.rating)+'</div></div><button type="button" data-id="'+escapeHtml(b.id)+'" aria-label="Open '+escapeHtml(b.title)+'">Open</button></article>').join("");
  grid.querySelectorAll("button[data-id]").forEach(btn=>btn.addEventListener("click",()=>openDetail(btn.dataset.id)));
}
async function api(path){
  const r=await fetch(path,{headers:{"Accept":"application/json"}});
  const data=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(data&&data.error&&data.error.message?data.error.message:"Request failed ("+r.status+")");
  return data;
}
async function loadHealth(){
  try{const h=await api("/health");$("#healthText").textContent="API online";$("#modeValue").textContent=h.mode||"—"}
  catch(e){$("#healthText").textContent="API unavailable";$("#modeValue").textContent="—"}
}
async function loadCategories(){
  try{
    const data=await api("/v1/categories");
    const box=$("#categoryList");
    box.innerHTML=data.items.map(c=>'<button class="category-button" data-id="'+escapeHtml(c.id)+'">'+escapeHtml(c.name)+'</button>').join("");
    box.querySelectorAll("button").forEach(btn=>btn.addEventListener("click",()=>{state.category=btn.dataset.id;state.page=1;state.search=null;$("#searchInput").value="";updateCategoryUI();loadBooks()}));
  }catch(e){$("#categoryList").innerHTML='<div class="notice">'+escapeHtml(e.message)+'</div>'}
}
function updateCategoryUI(){document.querySelectorAll(".category-button").forEach(b=>b.classList.toggle("active",b.dataset.id===state.category))}
async function loadBooks(){
  clearNotice();grid.innerHTML='<div class="empty">Loading catalogue…</div>';
  try{
    let data;
    if(state.search){
      const params=new URLSearchParams({q:state.search,start_page:String(state.page),max_pages:"2"});
      if(state.category)params.set("category",state.category);
      data=await api("/v1/search?"+params.toString());
      renderBooks(data.items);
      resultLabel.textContent=data.matched_in_scan+" match"+(data.matched_in_scan===1?"":"es")+" in "+data.scanned_pages+" scanned page"+(data.scanned_pages===1?"":"s");
      sourceLabel.textContent=data.complete?"Complete fixture scan":"Bounded fixture scan";
      $("#prevButton").disabled=true;$("#nextButton").disabled=true;
      $("#pageLabel").textContent="Pages 1–2";
      state.bookPage={next_page:null,previous_page:null};
    }else{
      const params=new URLSearchParams({page:String(state.page)});
      if(state.category)params.set("category",state.category);
      data=await api("/v1/books?"+params.toString());
      state.bookPage=data;renderBooks(data.items);
      resultLabel.textContent=data.total_items+" books · showing page "+data.page;
      sourceLabel.textContent=data.source.mode+" · "+(data.source.cache_hit?"cache hit":"fresh fixture read");
      $("#prevButton").disabled=!data.previous_page;
      const fixtureStopsHere=data.source.mode==="fixture"&&data.page>=2;
      $("#nextButton").disabled=!data.next_page||fixtureStopsHere;
      $("#pageLabel").textContent="Page "+data.page+" of "+data.total_pages;
    }
  }catch(e){renderBooks([]);showNotice(e.message);resultLabel.textContent="Unable to load this fixture slice";sourceLabel.textContent=""}
}
async function openDetail(id){
  const dialog=$("#detailDialog"),content=$("#detailContent");
  content.innerHTML='<div class="detail"><p>Loading book details…</p></div>';dialog.showModal();
  try{
    const data=await api("/v1/books/"+encodeURIComponent(id)),item=data.item,source=data.source;
    content.innerHTML='<article class="detail"><span class="detail-kicker">'+escapeHtml(item.category&&item.category.name?item.category.name:"Book detail")+'</span><h2>'+escapeHtml(item.title)+'</h2><div class="detail-meta"><span class="pill">'+stars(item.rating)+'</span><span class="pill">'+(item.in_stock?"In stock":"Out of stock")+'</span><span class="pill">UPC '+escapeHtml(item.upc)+'</span></div><p>'+escapeHtml(item.description||"No description was published for this title.")+'</p><div class="detail-grid"><div class="detail-stat"><span>Price</span><strong>'+money(item.price)+'</strong></div><div class="detail-stat"><span>Tax</span><strong>'+money(item.tax)+'</strong></div><div class="detail-stat"><span>Stock count</span><strong>'+escapeHtml(item.stock_count)+'</strong></div><div class="detail-stat"><span>Reviews</span><strong>'+escapeHtml(item.review_count)+'</strong></div><div class="detail-stat"><span>Mode</span><strong>'+escapeHtml(source.mode)+'</strong></div><div class="detail-stat"><span>Captured</span><strong>'+new Date(source.fetched_at).toLocaleDateString()+'</strong></div></div></article>';
  }catch(e){
    const item=state.currentBooks[id];
    if(item){
      content.innerHTML='<article class="detail"><span class="detail-kicker">Catalogue summary</span><h2>'+escapeHtml(item.title)+'</h2><div class="detail-meta"><span class="pill">'+stars(item.rating)+'</span><span class="pill">'+(item.in_stock?"In stock":"Out of stock")+'</span></div><p>This public demo uses a small set of captured source pages so it stays deterministic and does not scrape the live catalogue. A full captured detail page is included for the example title “A Light in the Attic”; other cards still show their verified list-page data here.</p><div class="detail-grid"><div class="detail-stat"><span>Price</span><strong>'+money(item.price)+'</strong></div><div class="detail-stat"><span>Rating</span><strong>'+escapeHtml(item.rating)+' / 5</strong></div><div class="detail-stat"><span>Availability</span><strong>'+(item.in_stock?"In stock":"Out of stock")+'</strong></div></div></article>';
    }else{
      content.innerHTML='<div class="detail"><h2>Could not load details</h2><p>'+escapeHtml(e.message)+'</p></div>';
    }
  }
}
$("#searchButton").addEventListener("click",()=>{state.search=$("#searchInput").value.trim()||null;state.page=1;loadBooks()});
$("#searchInput").addEventListener("keydown",e=>{if(e.key==="Enter")$("#searchButton").click()});
$("#clearCategory").addEventListener("click",()=>{state.category=null;state.page=1;updateCategoryUI();loadBooks()});
$("#prevButton").addEventListener("click",()=>{if(state.search){state.page=Math.max(1,state.page-2)}else if(state.bookPage&&state.bookPage.previous_page){state.page=state.bookPage.previous_page}loadBooks()});
$("#nextButton").addEventListener("click",()=>{if(state.bookPage&&state.bookPage.next_page){state.page=state.bookPage.next_page;loadBooks()}});
$("#closeDialog").addEventListener("click",()=>$("#detailDialog").close());
$("#detailDialog").addEventListener("click",e=>{if(e.target===$("#detailDialog"))$("#detailDialog").close()});
loadHealth();loadCategories();loadBooks();