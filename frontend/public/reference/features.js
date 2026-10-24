(()=>{
 const examples={
  shortlist:{question:'What should I research before choosing stocks to buy?',answer:'Start with your goals, time horizon, and comfort with risk. Then compare how the businesses make money, their financial results, valuation, and upcoming events. Use the graph to explore each candidate’s context before forming a view.',tags:['Company results','Related sectors','Upcoming events']},
  connections:{question:'How would I understand the context around a stock?',answer:'Start at the company node. Follow its sector, earnings, news, and macro connections, then inspect the evidence and timing behind each relationship. A connection gives you a research question to investigate; it does not establish what caused a price move.',tags:['Knowledge graph','Source evidence','Event windows']},
  learn:{question:'What is the difference between a stock and a sector?',answer:'A stock represents an ownership interest in a company. A sector groups companies with similar economic activities. Looking at both helps you compare a business with its wider industry context.',tags:['Company','Industry context','Related companies']}
 };
 document.querySelectorAll('[data-chat-example]').forEach(button=>button.addEventListener('click',()=>{
  const example=examples[button.dataset.chatExample];
  document.querySelectorAll('[data-chat-example]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  document.getElementById('chat-question').textContent=example.question;document.getElementById('chat-answer').textContent=example.answer;
  const tags=document.getElementById('chat-context-tags');tags.replaceChildren(...example.tags.map(tag=>{const span=document.createElement('span');span.textContent=tag;return span;}));
 }));
 const run=document.getElementById('bot-run'),preview=document.querySelector('.bot-preview');let shown=false;
 run.addEventListener('click',()=>{shown=!shown;preview.classList.toggle('sample-complete',shown);run.setAttribute('aria-pressed',String(shown));run.replaceChildren(document.createTextNode(shown?'Reset sample':'Run sample check'));const arrow=document.createElement('span');arrow.textContent=shown?'↺':'↗';run.append(arrow);
  document.getElementById('bot-result-status').textContent=shown?'EXAMPLE SIGNAL / REVIEW REQUIRED':'READY TO PREVIEW';
  document.getElementById('bot-result-copy').textContent=shown?'Sample condition matched and example limits checked. The proposed order is held for your review. No order has been sent.':'See how an example signal moves through the planned bot workflow.';
 });
})();
