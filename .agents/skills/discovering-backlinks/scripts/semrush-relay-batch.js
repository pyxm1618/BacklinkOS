/* BacklinkOS verified Semrush relay runner
 * Runs inside an authenticated https://sem.3ue.com Backlink Analytics page.
 * Verified contracts (2026-08-21):
 *   Organic Traffic: GET /analytics/backlinks/webapi2/organic-traffic?domain=<domain>&key=<session>&_=<ts>
 *   Referring Domains: GET /analytics/backlinks/webapi2/?action=report&type=backlinks_refdomains&target=<domain>&target_type=root_domain&display_page=<n>&sort_field=domain_ascore&sort_type=desc&key=<session>&_=<ts>
 *
 * Security: key / cookies / __gmitm are used only in memory and never written to logs or output files.
 */

(() => {
  const VERSION = '2026-08-21.2';
  const KEY_RE = /^[a-f0-9]{32}$/i;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function normalizeDomain(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, '')
      .replace(/^www\./, '')
      .split('/')[0]
      .split('?')[0]
      .split('#')[0];
  }

  function uniqueDomains(domains) {
    return [...new Set((domains || []).map(normalizeDomain).filter(Boolean))];
  }

  function redactUrl(raw) {
    try {
      const u = new URL(raw, location.origin);
      if (u.searchParams.has('key')) u.searchParams.set('key', '[REDACTED]');
      if (u.searchParams.has('__gmitm')) u.searchParams.set('__gmitm', '[REDACTED]');
      return u.pathname + u.search;
    } catch {
      return String(raw)
        .replace(/([?&]key=)[^&]+/gi, '$1[REDACTED]')
        .replace(/([?&]__gmitm=)[^&]+/gi, '$1[REDACTED]');
    }
  }

  function downloadJson(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
  }

  function toIsoOrNull(unixSeconds) {
    if (typeof unixSeconds !== 'number' || !Number.isFinite(unixSeconds)) return null;
    try {
      return new Date(unixSeconds * 1000).toISOString();
    } catch {
      return null;
    }
  }

  function collectHex32(text, out) {
    if (typeof text !== 'string' || !text) return;
    const matches = text.match(/\b[a-f0-9]{32}\b/gi);
    if (!matches) return;
    for (const m of matches) out.add(m);
  }

  async function validateSessionKey(key, preflightDomain) {
    if (!KEY_RE.test(String(key || ''))) return false;

    const u = new URL('/analytics/backlinks/webapi2/organic-traffic', location.origin);
    u.searchParams.set('domain', preflightDomain);
    u.searchParams.set('key', key);
    u.searchParams.set('_', String(Date.now()));

    try {
      const res = await fetch(u.toString(), {
        method: 'GET',
        credentials: 'include',
        cache: 'no-store',
      });
      if (!res.ok) return false;

      const text = await res.text();
      let data;
      try { data = JSON.parse(text); } catch { return false; }

      return !!data && typeof data === 'object';
    } catch {
      return false;
    }
  }

  async function resolveSessionKey(preflightDomain) {
    if (KEY_RE.test(String(window.__BACKLINKOS_SEM_KEY || ''))) {
      if (await validateSessionKey(window.__BACKLINKOS_SEM_KEY, preflightDomain)) {
        return { key: window.__BACKLINKOS_SEM_KEY, source: 'window_cache' };
      }
      try { delete window.__BACKLINKOS_SEM_KEY; } catch {}
    }

    const candidates = new Set();

    for (const entry of performance.getEntriesByType('resource')) {
      const raw = entry?.name || '';
      if (!raw.includes('/analytics/backlinks/webapi2')) continue;
      try {
        const u = new URL(raw, location.origin);
        const key = u.searchParams.get('key');
        if (KEY_RE.test(String(key || ''))) candidates.add(key);
      } catch {}
    }

    for (let i = 0; i < localStorage.length; i++) {
      collectHex32(localStorage.getItem(localStorage.key(i)), candidates);
    }
    for (let i = 0; i < sessionStorage.length; i++) {
      collectHex32(sessionStorage.getItem(sessionStorage.key(i)), candidates);
    }
    collectHex32(document.cookie || '', candidates);
    document.querySelectorAll('script:not([src])').forEach((s) => collectHex32(s.textContent || '', candidates));

    const seen = new WeakSet();
    let scanned = 0;
    const MAX_OBJECTS = 30000;
    const MAX_DEPTH = 4;

    function walk(value, depth) {
      if (scanned >= MAX_OBJECTS || depth > MAX_DEPTH) return;
      if (typeof value === 'string') {
        collectHex32(value, candidates);
        return;
      }
      if (!value || (typeof value !== 'object' && typeof value !== 'function')) return;
      if (typeof Node !== 'undefined' && value instanceof Node) return;

      try {
        if (seen.has(value)) return;
        seen.add(value);
      } catch {
        return;
      }

      scanned++;
      let keys;
      try { keys = Object.getOwnPropertyNames(value); } catch { return; }

      for (let i = 0; i < keys.length && i < 300; i++) {
        let child;
        try { child = value[keys[i]]; } catch { continue; }
        if (typeof child === 'string') collectHex32(child, candidates);
        else if (child && (typeof child === 'object' || typeof child === 'function')) walk(child, depth + 1);
      }
    }

    walk(window, 0);

    for (const candidate of candidates) {
      if (await validateSessionKey(candidate, preflightDomain)) {
        window.__BACKLINKOS_SEM_KEY = candidate;
        return { key: candidate, source: 'verified_candidate_scan', candidate_count: candidates.size };
      }
    }

    return { key: null, source: 'not_found', candidate_count: candidates.size, scanned_objects: scanned };
  }

  async function runBacklinkOSSemrush(userConfig = {}) {
    if (location.hostname !== 'sem.3ue.com') {
      throw new Error('必须在已经登录的 sem.3ue.com Backlink Analytics 页面运行。');
    }

    const config = {
      batchId: userConfig.batchId || `B${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`,
      domains: uniqueDomains(userConfig.domains),
      trafficMin: Number.isFinite(userConfig.trafficMin) ? userConfig.trafficMin : 500,
      delayMs: Number.isFinite(userConfig.delayMs) ? Math.max(0, userConfig.delayMs) : 650,
      preflightDomain: normalizeDomain(userConfig.preflightDomain || new URL(location.href).searchParams.get('q') || 'obby.fun'),
      maxRdRowsPerProject:
        Number.isFinite(userConfig.maxRdRowsPerProject) && userConfig.maxRdRowsPerProject > 0
          ? Math.floor(userConfig.maxRdRowsPerProject)
          : null,
      requestRetries: Number.isFinite(userConfig.requestRetries)
        ? Math.max(0, Math.floor(userConfig.requestRetries))
        : 3,
    };

    if (!config.domains.length) {
      throw new Error('domains 为空。示例：runBacklinkOSSemrush({batchId:"B20260821-002", domains:["example.com"]})');
    }

    console.clear();
    console.log(`🚀 BacklinkOS Semrush Runner ${VERSION}`);
    console.log(`Batch=${config.batchId} | candidates=${config.domains.length} | trafficMin=${config.trafficMin}`);

    const session = await resolveSessionKey(config.preflightDomain);
    if (!session.key) {
      const diagnostic = {
        kind: 'semrush_preflight_failure',
        runner_version: VERSION,
        generated_at: new Date().toISOString(),
        batch_id: config.batchId,
        current_page: redactUrl(location.href),
        reason: 'session_key_not_found_after_verified_recovery',
        key_recovery: {
          source: session.source,
          candidate_count: session.candidate_count ?? 0,
          scanned_objects: session.scanned_objects ?? null,
        },
      };
      downloadJson(diagnostic, `BacklinkOS-${config.batchId}-semrush-diagnostic-${Date.now()}.json`);
      throw new Error('未恢复到有效 Semrush session key。已下载脱敏诊断文件；不要手工猜 key。');
    }

    const sessionKey = session.key;

    async function getJson(path, params, attempt = 0) {
      const u = new URL(path, location.origin);
      const finalParams = { ...params, key: sessionKey, _: Date.now() };
      for (const [k, v] of Object.entries(finalParams)) {
        if (v !== undefined && v !== null) u.searchParams.set(k, String(v));
      }

      const res = await fetch(u.toString(), {
        method: 'GET',
        credentials: 'include',
        cache: 'no-store',
      });
      const text = await res.text();
      let data = text;
      try { data = JSON.parse(text); } catch {}

      if ((res.status === 429 || res.status >= 500) && attempt < config.requestRetries) {
        await sleep(1200 * (attempt + 1));
        return getJson(path, params, attempt + 1);
      }

      return { httpStatus: res.status, ok: res.ok, url: redactUrl(u.toString()), data };
    }

    async function queryOrganic(domain) {
      const r = await getJson('/analytics/backlinks/webapi2/organic-traffic', { domain });
      if (!r.ok) {
        return {
          status: r.httpStatus === 401 || r.httpStatus === 403 ? 'session_error' : 'http_error',
          domain,
          http_status: r.httpStatus,
          request_url: r.url,
          organic_traffic: null,
          databases: null,
          error: `HTTP ${r.httpStatus}`,
        };
      }

      if (typeof r.data?.organic_traffic === 'number' && Number.isFinite(r.data.organic_traffic)) {
        return {
          status: 'value',
          domain,
          http_status: r.httpStatus,
          organic_traffic: r.data.organic_traffic,
          databases: r.data.databases || {},
        };
      }

      if (r.data && typeof r.data === 'object') {
        return {
          status: 'no_data',
          domain,
          http_status: r.httpStatus,
          organic_traffic: null,
          databases: r.data.databases || null,
        };
      }

      return {
        status: 'schema_error',
        domain,
        http_status: r.httpStatus,
        organic_traffic: null,
        databases: null,
        error: 'HTTP 200 but response is not an object',
      };
    }

    async function queryRefDomains(domain, page) {
      const r = await getJson('/analytics/backlinks/webapi2/', {
        action: 'report',
        type: 'backlinks_refdomains',
        target: domain,
        target_type: 'root_domain',
        display_page: page,
        sort_field: 'domain_ascore',
        sort_type: 'desc',
      });

      if (!r.ok) {
        return {
          status: r.httpStatus === 401 || r.httpStatus === 403 ? 'session_error' : 'http_error',
          domain,
          page,
          http_status: r.httpStatus,
          request_url: r.url,
          error: `HTTP ${r.httpStatus}`,
        };
      }

      if (r.data?.status !== 'SUCCESS' || !r.data?.refdomains || !Array.isArray(r.data.refdomains.data)) {
        return {
          status: 'schema_error',
          domain,
          page,
          http_status: r.httpStatus,
          error: 'HTTP 成功，但响应不是预期的 refdomains SUCCESS 结构',
        };
      }

      return {
        status: 'value',
        domain,
        page,
        http_status: r.httpStatus,
        total: Number(r.data.refdomains.total || 0),
        limit: Number(r.data.refdomains.limit || 100),
        offset: Number(r.data.refdomains.offset || 0),
        rows: r.data.refdomains.data,
      };
    }

    function failPreflight(reason, detail) {
      const diagnostic = {
        kind: 'semrush_preflight_failure',
        runner_version: VERSION,
        generated_at: new Date().toISOString(),
        batch_id: config.batchId,
        current_page: redactUrl(location.href),
        reason,
        detail,
      };
      downloadJson(diagnostic, `BacklinkOS-${config.batchId}-semrush-diagnostic-${Date.now()}.json`);
      throw new Error(`Semrush preflight 失败：${reason}。已下载脱敏诊断 JSON。`);
    }

    const preOrganic = await queryOrganic(config.preflightDomain);
    if (!['value', 'no_data'].includes(preOrganic.status)) {
      failPreflight('organic_contract_failed', preOrganic);
    }
    await sleep(config.delayMs);

    const preRd = await queryRefDomains(config.preflightDomain, 0);
    if (preRd.status !== 'value') {
      failPreflight('refdomains_contract_failed', preRd);
    }

    console.log(`✅ Preflight passed | keySource=${session.source} | organic=${preOrganic.status} | RD total=${preRd.total}`);

    const output = {
      batch_id: config.batchId,
      runner_version: VERSION,
      generated_at: new Date().toISOString(),
      settings: {
        traffic_min: config.trafficMin,
        candidate_count: config.domains.length,
        max_rd_rows_per_project: config.maxRdRowsPerProject,
        organic_traffic_semantics: 'global / total across returned databases',
        country_traffic_semantics: 'response.databases[country]',
        session_key_source: session.source,
      },
      precheck: {
        domain: config.preflightDomain,
        organic_status: preOrganic.status,
        organic_traffic: preOrganic.organic_traffic,
        rd_total: preRd.total,
        rd_page0_rows: preRd.rows.length,
      },
      projects: [],
      refdomain_rows: [],
      refdomain_aggregates: [],
      errors: [],
      warnings: [],
    };

    for (let i = 0; i < config.domains.length; i++) {
      const domain = config.domains[i];
      console.log(`[Organic ${i + 1}/${config.domains.length}] ${domain}`);

      const organic = await queryOrganic(domain);
      const qualified = organic.status === 'value' && organic.organic_traffic >= config.trafficMin;
      const project = {
        domain,
        organic_status: organic.status,
        organic_traffic: organic.organic_traffic,
        organic_traffic_by_db: organic.databases,
        qualified,
        referring_domains_total: null,
        referring_domains_fetched: 0,
        rd_pages_fetched: 0,
        rd_complete: false,
      };
      output.projects.push(project);

      if (organic.status === 'value') {
        console.log(`  → Global=${organic.organic_traffic}, US=${organic.databases?.us ?? 'N/A'} ${qualified ? '✅ qualified' : '⏭️ below threshold'}`);
      } else if (organic.status === 'no_data') {
        console.log('  → no_data（HTTP 200；Semrush 未给 Organic Traffic，不计入 error）');
      } else {
        output.errors.push({ stage: 'organic', domain, ...organic });
        console.warn(`  ❌ ${organic.status}: ${organic.error || ''}`);
      }

      await sleep(config.delayMs);
    }

    const qualifiedProjects = output.projects.filter((p) => p.qualified);
    console.log(`✅ Organic finished: qualified=${qualifiedProjects.length}/${output.projects.length}`);

    for (let i = 0; i < qualifiedProjects.length; i++) {
      const project = qualifiedProjects[i];
      const merged = new Map();
      let page = 0;
      let reportedTotal = null;
      let limit = 100;
      let stoppedByCap = false;
      let previousOffset = -1;

      console.log(`[RD ${i + 1}/${qualifiedProjects.length}] ${project.domain}`);

      while (true) {
        if (config.maxRdRowsPerProject && merged.size >= config.maxRdRowsPerProject) {
          stoppedByCap = true;
          break;
        }

        const rd = await queryRefDomains(project.domain, page);
        if (rd.status !== 'value') {
          output.errors.push({ stage: 'refdomains', domain: project.domain, page, ...rd });
          break;
        }

        reportedTotal = rd.total;
        limit = rd.limit || 100;

        if (page > 0 && rd.offset <= previousOffset) {
          output.errors.push({
            stage: 'refdomains',
            domain: project.domain,
            page,
            status: 'pagination_error',
            error: `offset did not advance: previous=${previousOffset}, current=${rd.offset}`,
          });
          break;
        }
        previousOffset = rd.offset;

        let added = 0;
        for (const row of rd.rows) {
          const refDomain = normalizeDomain(row?.domain);
          if (!refDomain || merged.has(refDomain)) continue;
          if (config.maxRdRowsPerProject && merged.size >= config.maxRdRowsPerProject) {
            stoppedByCap = true;
            break;
          }

          merged.set(refDomain, {
            source_project: project.domain,
            source_project_organic_traffic: project.organic_traffic,
            source_project_us_organic_traffic: project.organic_traffic_by_db?.us ?? null,
            referring_domain: refDomain,
            backlinks_num: row.backlinks_num ?? null,
            domain_ascore: row.domain_ascore ?? null,
            first_seen: row.first_seen ?? null,
            first_seen_iso: toIsoOrNull(row.first_seen),
            last_seen: row.last_seen ?? null,
            last_seen_iso: toIsoOrNull(row.last_seen),
            ip: row.ip ?? null,
            country: row.country ?? '',
            category: row.category ?? '',
            lost: row.lost ?? false,
            new: row.new ?? false,
            is_follow: row.is_follow ?? null,
          });
          added++;
        }

        project.rd_pages_fetched++;
        console.log(`  page ${page}: rows=${rd.rows.length}, +${added}, offset=${rd.offset}, total=${reportedTotal}`);

        if (stoppedByCap) break;
        if (merged.size >= reportedTotal) break;
        if (rd.rows.length < limit) break;
        if (added === 0) {
          output.errors.push({
            stage: 'refdomains',
            domain: project.domain,
            page,
            status: 'pagination_error',
            error: 'page returned no new referring domains',
          });
          break;
        }

        page++;
        await sleep(config.delayMs);
      }

      project.referring_domains_total = reportedTotal;
      project.referring_domains_fetched = merged.size;
      project.rd_complete = reportedTotal !== null && merged.size >= reportedTotal;

      if (stoppedByCap && !project.rd_complete) {
        output.warnings.push({
          stage: 'refdomains',
          domain: project.domain,
          warning: 'intentional_cap_reached',
          fetched: merged.size,
          total: reportedTotal,
        });
      }

      output.refdomain_rows.push(...merged.values());
      console.log(`  → RD ${merged.size}/${reportedTotal ?? '?'} ${project.rd_complete ? '✅ complete' : '⚠️ partial'}`);
      await sleep(config.delayMs);
    }

    const aggregateMap = new Map();
    for (const row of output.refdomain_rows) {
      const key = row.referring_domain;
      if (!aggregateMap.has(key)) {
        aggregateMap.set(key, {
          referring_domain: key,
          source_projects: [],
          source_project_organic_traffic: {},
          successful_project_count: 0,
          occurrence_count: 0,
          backlinks_num: null,
          domain_ascore: null,
          first_seen: null,
          last_seen: null,
          follow_observation_count: 0,
          nofollow_observation_count: 0,
          semrush_is_follow: null,
          discovery_source: 'Semrush Backlink Analytics via sem.3ue.com',
          batch_id: config.batchId,
          first_discovered_at: output.generated_at,
          seen_before: null,
        });
      }

      const a = aggregateMap.get(key);
      a.occurrence_count++;
      if (!a.source_projects.includes(row.source_project)) a.source_projects.push(row.source_project);
      a.source_project_organic_traffic[row.source_project] = row.source_project_organic_traffic;
      a.successful_project_count = a.source_projects.length;
      if (typeof row.backlinks_num === 'number') a.backlinks_num = Math.max(a.backlinks_num ?? 0, row.backlinks_num);
      if (typeof row.domain_ascore === 'number') a.domain_ascore = Math.max(a.domain_ascore ?? 0, row.domain_ascore);
      if (typeof row.first_seen === 'number') a.first_seen = a.first_seen == null ? row.first_seen : Math.min(a.first_seen, row.first_seen);
      if (typeof row.last_seen === 'number') a.last_seen = a.last_seen == null ? row.last_seen : Math.max(a.last_seen, row.last_seen);
      if (row.is_follow === true) a.follow_observation_count++;
      if (row.is_follow === false) a.nofollow_observation_count++;
    }

    for (const a of aggregateMap.values()) {
      if (a.follow_observation_count && a.nofollow_observation_count) a.semrush_is_follow = 'mixed';
      else if (a.follow_observation_count) a.semrush_is_follow = true;
      else if (a.nofollow_observation_count) a.semrush_is_follow = false;
      output.refdomain_aggregates.push(a);
    }

    output.refdomain_aggregates.sort((a, b) =>
      b.successful_project_count - a.successful_project_count ||
      (b.domain_ascore ?? -1) - (a.domain_ascore ?? -1) ||
      a.referring_domain.localeCompare(b.referring_domain)
    );

    const organicValue = output.projects.filter((p) => p.organic_status === 'value').length;
    const organicNoData = output.projects.filter((p) => p.organic_status === 'no_data').length;
    const rdComplete = output.projects.filter((p) => p.qualified && p.rd_complete).length;
    const rdPartial = output.projects.filter((p) => p.qualified && !p.rd_complete).length;

    output.summary = {
      candidate_projects: output.projects.length,
      organic_value: organicValue,
      organic_no_data: organicNoData,
      qualified_projects: qualifiedProjects.length,
      rd_complete_projects: rdComplete,
      rd_partial_projects: rdPartial,
      raw_refdomain_rows: output.refdomain_rows.length,
      unique_referring_domains: output.refdomain_aggregates.length,
      true_errors: output.errors.length,
      warnings: output.warnings.length,
    };

    const filename = `BacklinkOS-${config.batchId}-FINAL-${Date.now()}.json`;
    downloadJson(output, filename);
    console.log('====================================');
    console.log(`✅ 完成并下载：${filename}`);
    console.table(output.summary);
    console.log('====================================');
    return output;
  }

  window.runBacklinkOSSemrush = runBacklinkOSSemrush;
  console.log(`✅ BacklinkOS Semrush Runner ${VERSION} loaded`);
  console.log('调用：runBacklinkOSSemrush({batchId:"B20260821-002", domains:["example.com"]})');
})();
