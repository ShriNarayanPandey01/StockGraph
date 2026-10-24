"use strict";
const form=document.querySelector("#query-form"), statusBox=document.querySelector("#status"), results=document.querySelector("#results"), list=document.querySelector("#connections"), more=document.querySelector("#more"), kind=document.querySelector("#kind");
let nodes=new Map(), edges=new Map(), nextOffset=null, snapshot=null, query=null, busy=false, generation=0;
const label=node=>node?.properties?.name||node?.properties?.title||node?.properties?.headline||node?.properties?.ticker||node?.properties?.id||node?.id||"Unknown entity";
const text=(tag,value,className)=>{const element=document.createElement(tag);element.textContent=value;if(className)element.className=className;return element;};
function setStatus(message,error=false){statusBox.textContent=message;statusBox.className=error?"error":"";}
function safeUrl(value){try{const url=new URL(value);return ["https:","http:"].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}}
function render(){
  list.replaceChildren();let count=0;
  for(const edge of edges.values()){
    const source=nodes.get(edge.source),target=nodes.get(edge.target);
    if(kind.value!=="all"&&!([source?.kind,target?.kind].includes(kind.value)))continue;
    const other=source?.kind==="Stock"&&source?.properties?.ticker===query.ticker?target:source;
    const card=document.createElement("article");card.className="connection";
    const heading=document.createElement("div");heading.append(text("span",other?.kind||"Relationship","kind"),text("h3",label(other)));card.append(heading);
    if(typeof edge.confidence==="number")card.append(text("span",`${Math.round(edge.confidence*100)}% extraction confidence`,"confidence"));
    card.append(text("p",`${label(source)} → ${edge.relation.replaceAll("_"," ")} → ${label(target)}`,"relation"));
    if(edge.rationale)card.append(text("p",edge.rationale));
    const details=document.createElement("details");details.append(text("summary","Inspect evidence and timestamps"));
    const properties={...(other?.properties||{}),...(edge.properties||{})};
    delete properties.embedding;delete properties.profile_embedding;
    details.append(text("pre",JSON.stringify(properties,null,2)));card.append(details);
    const evidence=other?.properties?.evidence||other?.properties?.evidence_json;
    let references=Array.isArray(evidence)?evidence:[];
    if(typeof evidence==="string"){try{references=JSON.parse(evidence);}catch{references=[];}}
    for(const url of [edge.provenance?.source_url,other?.properties?.source_url,...references.map(item=>item.url)].filter(Boolean)){
      const href=safeUrl(url);if(!href)continue;const a=text("a","Open source ↗","source");a.href=href;a.target="_blank";a.rel="noopener noreferrer";card.append(a);
    }
    list.append(card);count++;
  }
  if(!count)list.append(text("p",nextOffset!==null?"No matching connections in the loaded pages. Load more or choose another type.":"No connections of this type are available in this window."));
  document.querySelector("#count").textContent=`${count} loaded connection${count===1?"":"s"}`;
}
async function load(offset=0){
  if(busy)return;busy=true;const requestGeneration=generation;form.querySelector("button").disabled=true;more.disabled=true;list.setAttribute("aria-busy","true");setStatus("Loading graph evidence…");
  try{
    const params=new URLSearchParams({window:query.window,limit:"50",offset:String(offset)});if(snapshot!==null)params.set("as_of_ts",String(snapshot));
    const response=await fetch(`/api/v1/stocks/${encodeURIComponent(query.ticker)}/connections?${params}`,{headers:{Authorization:`Bearer ${document.querySelector("#token").value}`},cache:"no-store"});
    const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:`Request failed (${response.status}).`);
    if(requestGeneration!==generation)return;
    for(const node of data.nodes)nodes.set(node.id,node);for(const edge of data.edges)edges.set(edge.id,edge);
    nextOffset=data.pagination.next_offset;snapshot=data.pagination.as_of_ts;results.hidden=false;more.hidden=nextOffset===null;
    document.querySelector("#stock-label").textContent=data.ticker;
    document.querySelector("#snapshot").textContent=`Snapshot ${new Date(snapshot*1000).toLocaleString("en-IN",{timeZone:"Asia/Kolkata"})} IST`;
    const state=data.processing_status;
    setStatus(state==="completed"?nextOffset===null?"All available connections loaded.":"More connections are available.":`Processing status: ${state}. This graph may be incomplete; refresh after processing finishes.`);
    render();
  }catch(error){setStatus(`${error.message} Retry by selecting Explore connections.`,true);}finally{busy=false;form.querySelector("button").disabled=false;more.disabled=false;list.removeAttribute("aria-busy");}
}
form.addEventListener("submit",event=>{event.preventDefault();if(busy)return;generation++;nodes=new Map();edges=new Map();nextOffset=null;snapshot=null;results.hidden=true;query={ticker:document.querySelector("#ticker").value.trim().toUpperCase(),window:document.querySelector("#window").value};load();});
more.addEventListener("click",()=>{if(nextOffset!==null)load(nextOffset);});kind.addEventListener("change",()=>{if(query)render();});
