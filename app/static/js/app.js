const form = document.getElementById('consulta-form');
const feedback = document.getElementById('feedback');
const resultado = document.getElementById('resultado');

function setFeedback(message, type = 'ok') {
  feedback.textContent = message;
  feedback.className = `feedback ${type}`;
  feedback.classList.remove('hidden');
}

function hideFeedback() {
  feedback.className = 'feedback hidden';
  feedback.textContent = '';
}

function field(label, value) {
  return `<div class="field"><span>${label}</span><strong>${value || '—'}</strong></div>`;
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderStatusBadge(status) {
  if (!status) return '';
  const labelByStatus = {
    alerts_found: 'Alertas localizados',
    no_alerts_found: 'Sem alertas encontrados',
    blocked_source: 'Fonte bloqueada',
    partial_result: 'Resultado parcial útil',
    manual_validation_required: 'Validação manual necessária',
  };
  const label = labelByStatus[status] || status;
  return `<p class="meta">Status da busca de alertas: <strong>${escapeHtml(label)}</strong></p>`;
}

function render(data) {
  const product = data.product || {};
  const status = data.alerts_status;
  const alerts = data.alerts || [];

  const fullAlerts = alerts.filter(a => Boolean(a.link_oficial || a.link));
  const partialAlerts = alerts.filter(a => !a.link_oficial && !a.link);
  const blockedWithoutId = status === 'blocked_source' && alerts.length === 0;

  const warningHtml = data.alerts_warning
    ? `<div class="feedback warning">${escapeHtml(data.alerts_warning)}</div>`
    : '';

  const sourceHtml = Array.isArray(data.alerts_sources) && data.alerts_sources.length
    ? `<details class="alerts-sources"><summary>Log técnico por estratégia</summary><ul>${data.alerts_sources.map(s => {
      const detail = s.details ? ` — ${escapeHtml(s.details)}` : '';
      const layer = s.layer ? `${escapeHtml(s.layer)} · ` : '';
      return `<li><strong>${layer}${escapeHtml(s.name || 'fonte')}</strong> (${escapeHtml(s.status || 'desconhecido')}) · alertas: ${escapeHtml(String(s.alerts_count || 0))}${s.url ? ` · <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer">abrir</a>` : ''}${detail}</li>`;
    }).join('')}</ul></details>`
    : '';

  const manualLinks = data.alerts_manual_links || {};
  const manualLinksHtml = Object.values(manualLinks).some(Boolean)
    ? `<div class="manual-links"><p>Consulta manual recomendada:</p><ul>
        ${manualLinks.principal ? `<li><a href="${escapeHtml(manualLinks.principal)}" target="_blank" rel="noopener noreferrer">Portal de alertas (legado)</a></li>` : ''}
        ${manualLinks.listagem ? `<li><a href="${escapeHtml(manualLinks.listagem)}" target="_blank" rel="noopener noreferrer">Listagem de alertas (legado)</a></li>` : ''}
        ${manualLinks.tecnovigilancia ? `<li><a href="${escapeHtml(manualLinks.tecnovigilancia)}" target="_blank" rel="noopener noreferrer">Página oficial de Tecnovigilância</a></li>` : ''}
        ${manualLinks.dados_abertos_tecnovigilancia ? `<li><a href="${escapeHtml(manualLinks.dados_abertos_tecnovigilancia)}" target="_blank" rel="noopener noreferrer">Dados abertos de Tecnovigilância</a></li>` : ''}
        ${manualLinks.busca_portal ? `<li><a href="${escapeHtml(manualLinks.busca_portal)}" target="_blank" rel="noopener noreferrer">Busca avançada legado</a></li>` : ''}
        ${manualLinks.busca_govbr ? `<li><a href="${escapeHtml(manualLinks.busca_govbr)}" target="_blank" rel="noopener noreferrer">Busca gov.br ANVISA</a></li>` : ''}
        ${manualLinks.sistec_historico ? `<li><a href="${escapeHtml(manualLinks.sistec_historico)}" target="_blank" rel="noopener noreferrer">Histórico SISTEC</a></li>` : ''}
        ${manualLinks.espelho_comunitario ? `<li><a href="${escapeHtml(manualLinks.espelho_comunitario)}" target="_blank" rel="noopener noreferrer">Espelho comunitário por registro</a></li>` : ''}
      </ul></div>`
    : '';

  const numbers = [...new Set(alerts.map(a => a.numero_alerta || a.id).filter(Boolean))];
  const alertNumbersHtml = numbers.length
    ? `<div class="manual-links"><p><strong>Números de alerta identificados:</strong></p><ul>${numbers.map(num => `
      <li><a href="https://www.gov.br/anvisa/pt-br/search?SearchableText=${encodeURIComponent(`alerta ${num} anvisa`)}" target="_blank" rel="noopener noreferrer">Alerta ${escapeHtml(num)}</a></li>
    `).join('')}</ul></div>`
    : '';

  const discoverySummaryHtml = `
    <p class="meta">
      Alerta completo: <strong>${fullAlerts.length}</strong>
      · Alerta parcialmente identificado: <strong>${partialAlerts.length}</strong>
      · Fonte bloqueada sem identificação: <strong>${blockedWithoutId ? 'sim' : 'não'}</strong>
    </p>
  `;

  let alertsHtml = '';
  if (alerts.length) {
    alertsHtml = alerts.map(a => {
      const isPartial = !a.link_oficial && !a.link;
      const numero = a.numero_alerta || a.id;
      return `
        <article class="alert-item ${isPartial ? 'alert-item-partial' : 'alert-item-full'}">
          <h4>${escapeHtml(a.title || a.titulo || (numero ? `Alerta ${numero}` : 'Alerta'))}</h4>
          <div class="meta">
            ${escapeHtml(a.date || a.data || 'Data não informada')}
            ${numero ? ` • <strong>Nº ${escapeHtml(numero)}</strong>` : ''}
            ${a.origem_da_descoberta ? ` • Origem: ${escapeHtml(a.origem_da_descoberta)}` : ''}
            ${a.metodo ? ` • Método: ${escapeHtml(a.metodo)}` : ''}
            ${a.nivel_confianca ? ` • Confiança: ${escapeHtml(a.nivel_confianca)}` : ''}
          </div>
          ${a.summary ? `<p>${escapeHtml(a.summary)}</p>` : ''}
          <div class="meta">
            ${a.link_oficial || a.link ? `<a href="${escapeHtml(a.link_oficial || a.link)}" target="_blank" rel="noopener noreferrer">${(a.metodo || '').startsWith('external_fallback.') ? 'Abrir referência externa' : 'Abrir link oficial'}</a>` : '<span>Alerta parcial (sem link oficial confirmado)</span>'}
            ${a.link_pesquisa_manual ? ` · <a href="${escapeHtml(a.link_pesquisa_manual)}" target="_blank" rel="noopener noreferrer">Pesquisar este alerta</a>` : ''}
          </div>
        </article>
      `;
    }).join('');
  } else if (status === 'no_alerts_found') {
    alertsHtml = '<p>Nenhum alerta de tecnovigilância encontrado para os termos consultados.</p>';
  } else if (status === 'blocked_source') {
    alertsHtml = '<p>Fontes oficiais bloquearam a consulta automática nesta execução. O sistema tentou estratégias indiretas e mantém links de contingência abaixo.</p>';
  } else {
    alertsHtml = '<p>A consulta automática não foi conclusiva, mas as estratégias e links de validação estão disponíveis abaixo.</p>';
  }

  resultado.innerHTML = `
    <div class="box">
      <h2>Dados do equipamento</h2>
      <div class="grid">
        ${field('Registro ANVISA', product.registro_anvisa || data.registro_anvisa)}
        ${field('Nome do produto', product.nome_produto)}
        ${field('Marca', product.marca)}
        ${field('Modelo', product.modelo)}
        ${field('Fabricante', product.fabricante)}
        ${field('Detentor do registro', product.detentor_registro)}
        ${field('País de fabricação', product.pais_fabricacao)}
        ${field('Situação', product.situacao)}
        ${field('Processo', product.processo)}
        ${field('Classificação de risco', product.classificacao_risco)}
      </div>
    </div>
    <div class="box">
      <h2>Alertas de tecnovigilância (${data.alerts_count || 0})</h2>
      ${renderStatusBadge(status)}
      ${warningHtml}
      ${discoverySummaryHtml}
      ${alertNumbersHtml}
      ${alertsHtml}
      ${sourceHtml}
      ${manualLinksHtml}
    </div>
  `;
  resultado.classList.remove('hidden');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  hideFeedback();
  resultado.classList.add('hidden');
  const registro = document.getElementById('registro').value.replace(/\D/g, '');

  if (registro.length !== 11) {
    setFeedback('O registro ANVISA deve conter exatamente 11 dígitos.', 'error');
    return;
  }

  setFeedback('Consultando fontes da Anvisa com estratégias em camadas...', 'ok');

  try {
    const response = await fetch(`/api/consultar?registro=${encodeURIComponent(registro)}`);
    const data = await response.json();

    if (!response.ok && data.error) {
      setFeedback(data.error, 'error');
      return;
    }

    if (!data.found) {
      setFeedback(data.message || 'Registro não encontrado.', 'error');
      return;
    }

    setFeedback(data.message || 'Consulta realizada com sucesso.', 'ok');
    render(data);
  } catch (err) {
    setFeedback('Falha ao consultar o sistema. Tente novamente.', 'error');
  }
});
