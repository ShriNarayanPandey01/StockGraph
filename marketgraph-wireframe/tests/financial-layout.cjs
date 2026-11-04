const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'../dist'),M=require(root+'/demo/model.js');
const pending={status:'In review',author:'A',version:2},eligible={verified:true,authorized:true,assigned:true};
assert.equal(M.transitionContribution(pending,'approve','B').status,'In review');
assert.equal(M.transitionContribution(pending,'approve','B',{...eligible,verified:false}).status,'In review');
assert.equal(M.transitionContribution(pending,'approve','B',{...eligible,assigned:false}).status,'In review');
assert.equal(M.transitionContribution(pending,'approve','A',eligible).status,'In review');
assert.equal(M.transitionContribution(pending,'approve','B',eligible).status,'Approved');
assert.equal(M.transitionContribution(pending,'reject','B',{authorized:true,assigned:true}).status,'Rejected');
assert.equal(M.transitionContribution(pending,'approve','A',{developer:true}).status,'Approved');
const els={},events={},store={};function el(id){return els[id]??={innerHTML:'',textContent:'',value:'',disabled:false,hidden:false,isConnected:true,classList:{remove(){},add(){}},offsetWidth:1,querySelector(){return null},focus(){},addEventListener(t,f){events[id+':'+t]=f},showModal(){},close(){}};}
let onHash;const loc={hash:'#dashboard'},document={querySelector:s=>el(s.slice(1)),activeElement:el('active')};
const sample={title:'Sample insight',body:'A detailed synthetic thesis with citations.',entity:'RELIANCE',direction:'Neutral',horizon:'1 month',event:'2026-10-26T10:00',expiry:'2099-01-01',url:'https://example.test/source',disclosures:'None declared',author:'Contributor A (sample)',version:2,status:'In review',versions:[]};store['marketgraph-v2-contribution']=JSON.stringify(sample);
vm.runInNewContext(fs.readFileSync(root+'/demo/workspace.js','utf8'),{window:{MarketGraphDemo:M},document,location:loc,localStorage:{getItem:k=>store[k]??null,setItem:(k,v)=>store[k]=v},Date,URL,console,clearTimeout(){},setTimeout(){return 1},addEventListener(t,f){if(t==='hashchange')onHash=f},FormData:class{constructor(f){this.data=f.data}*[Symbol.iterator](){yield*Object.entries(this.data)}}});
const html=()=>el('workspace-main').innerHTML;function route(v){loc.hash='#'+v;onHash();return html()}function role(r){events['role-preview:change']({target:{value:r}});if(loc.hash==='#dashboard')onHash();}function submit(id,data,extra={}){events['workspace-main:submit']({preventDefault(){},target:{id,data,...extra},submitter:extra.submitter});}

role('developer');route('stock/RELIANCE');
let h=html();const ids=['stock-graph','stock-history','stock-about','stock-fundamentals','stock-financials'];for(let i=1;i<ids.length;i++)assert(h.indexOf('id="'+ids[i-1]+'"')<h.indexOf('id="'+ids[i]+'"'),ids[i]+' order');
assert(/<\/section><section class="panel" id="stock-history"/.test(h),'history directly follows graph section');
assert(!h.includes('Numbers, with a timestamp.'));assert(!h.includes('Current stock'));assert(h.includes('stock-symbol-inline'));assert(h.includes('Quarterly'));assert(h.includes('Debt to equity'));
function click(d){const b={dataset:d,closest(){return this}};events['workspace-main:click']({target:b});}
click({finPeriod:'Quarterly'});assert(html().includes('Jun 23'));assert(html().includes('QUARTERLY SAMPLE'));assert(!html().includes('<th scope="col">FY20'));
click({finSeries:'Profit'});assert(html().includes('PROFIT / QUARTERLY SAMPLE'));click({finStatement:'Balance sheet'});assert(html().includes('<th scope="row">Total assets'));assert(!html().includes('<th scope="row">Tax expense'));
click({finStatement:'Cash flow'});assert(html().includes('<th scope="row">Cash from operations'));assert(html().includes('<th scope="row">Net cash movement'));
events['workspace-main:change']({target:{id:'financial-basis',value:'Standalone'}});assert(html().includes('Standalone · Synthetic series'));assert(html().includes('Cash flow · Standalone'));
click({finPeriod:'Yearly'});assert(html().includes('<th scope="col">FY24'));click({finStatement:'Income statement'});assert(html().includes('<th scope="row">EPS'));
route('stock/INDIGO');assert(html().includes('The negative sample profit denotes a loss'));assert(html().includes('P/E ratio'));assert(html().includes('N/A'));
route('stock/HDFCBANK');assert(!/undefined|NaN/.test(html()));route('stock/INFY');assert(!/undefined|NaN/.test(html()));
const idsFound=[...html().matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);assert.equal(idsFound.length,new Set(idsFound).size);
console.log('PASS: graph/history/business/financial order, history adjacency, combined heading, quarterly/yearly labels, metric switching, income/balance/cash statements, basis selection, loss/N-A state, generic company and unique IDs. DOM stub only.');
