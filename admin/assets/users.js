async function loadUsersPanel(){
  if(!state.api||!state.token){view('config');return}
  try{
    const [usersPayload,history]=await Promise.all([api('/api/admin/users'),api('/api/admin/history')]);
    const users=usersPayload.users||[],notes=history.notifications||[];
    $('#users-list').innerHTML=users.map(x=>`<div class="health"><div><span>${esc(x.name)} <small>· ${esc(x.role)}</small></span><b class="${x.active&&x.alerts_active?'ok':'neutral'}">${x.alerts_active?'Alertas ativos':'Alertas desativados'}</b></div><small>${x.favorites} favorito(s) · ${esc(x.status)} · última notificação: ${formatDateTime(x.last_notification)}</small></div>`).join('')||'<p class="empty">Nenhum usuário cadastrado foi encontrado.</p>';
    $('#notifications-list').innerHTML=notes.map(x=>`<div class="health"><div><span>${esc(x.type)}${x.ticker?' · '+esc(x.ticker):''}</span><b class="${x.audience==='ADMINISTRADOR'?'neutral':'ok'}">${esc(x.audience||'USUARIO')}</b></div><small>${esc(x.summary||x.error||'Sem detalhe')} · ${formatDateTime(x.sent_at||x.created_at)}</small></div>`).join('')||'<p class="empty">Nenhuma notificação persistida foi encontrada.</p>';
  }catch(e){const msg=`<p class="empty">${esc(e.message)}</p>`;$('#users-list').innerHTML=msg;$('#notifications-list').innerHTML=msg}
}
document.querySelector('.nav[data-view="usuarios"]')?.addEventListener('click',()=>loadUsersPanel());
document.querySelector('#refresh-users')?.addEventListener('click',loadUsersPanel);
