/* BacklinkOS verified Semrush relay runner
 * Runs inside an authenticated https://sem.3ue.com page.
 * Verified contracts recovered on 2026-08-21:
 *   Organic Traffic: GET /analytics/backlinks/webapi2/organic-traffic?domain=<domain>&key=<session>&_=<ts>
 *   Referring Domains: GET /analytics/backlinks/webapi2/?action=report&type=backlinks_refdomains&target=<domain>&target_type=root_domain&display_page=<n>&sort_field=domain_ascore&sort_type=desc&key=<session>&_=<ts>
 *
 * Security: session key / __gmitm are used only in memory and are never written to output.
 */

(() => {
  const VERSION = '2026-08-21.1';

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

  function findSessionKey() {
    const entries = performance.getEntriesByType('resource');
    for (let i = entries.length - 1; i >= 0; i--) {
      const raw = entries[i]?.name || '';
      if (!raw.includes('/analytics/backlinks/webapi2')) continue;
      try {
        const u = new URL(raw, location.origin);
        const key = u.searchParams.get('key');
        if (key) return key;
      } catch {}
    }
    return null;
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

  function toIsoOrNull(unixSeconds) {
    if (typeof unixSeconds !== 'number' || !Number.isFinite(unixSeconds)) return null;
    try {
      return new Date(unixSeconds * 1000).toISOString();
    } catch {
      return null;
    }
  }

  async function runBacklinkOSSemrush(userConfig = {}) {
    if (location.hostname !== 'sem.3ue.com') {
      throw new Error('必须在已经登录的 sem.3ue.com 页面运行。');
    }

    const config = {
      batchId: userConfig.batchId || `B${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`,
      domains: uniqueDomains(userConfig.domains),
      trafficMin: Number.isFinite(userConfig.trafficMin) ? userConfig.trafficMin : 500,
      delayMs: Number.isFinite(userConfig.delayMs) ? userConfig.delayMs : 650,
      preflightDomain: normalizeDomain(userConfig.preflightDomain || new URL(location.href).searchParams.get('q') || 'obby.fun'),
      // null => fetch all pages reported by Semrush. Set a positive integer only for an intentional cap.
      maxRdRowsPerProject: Number.isFinite(userConfig.maxRdRowsPerProject) && userConfig.maxRdRowsPerProject > 0
        ? Math.floor(userConfig.maxRdRowsPerProject)
        : null,
      requestRetries: Number.isFinite(userConfig.requestRetries) ? Math.max(0, Math.floor(userConfig.requestRetries)) : 3,
    };

    if (!config.domains.length) {
      throw new Error('domains 为空。调用示例：runBacklinkOSSemrush({batchId:"B20260821-001", domains:["example.com"]})');
    }

    const sessionKey = findSessionKey();
    if (!sessionKey) {
      const diagnostic = {
        kind: 'semrush_preflight_failure',
        runner_version: VERSION,
        generated_at: new Date().toISOString(),
        current_page: redactUrl(location.href),
        reason: 'session_key_not_found',
      };
      downloadJson(diagnostic, `BacklinkOS-${config.batchId}-semrush-diagnostic-${Date.now()}.json`);
      throw new Error('没有找到 Backlink Analytics session key。诊断 JSON 已自动下载。');
    }

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

      return {
        httpStatus: res.status,
        ok: res.ok,
        url: redactUrl(u.toString()),
        data,
      };
    }

    async function queryOrganic(domain) {
      const r = await getJson('/analytics/backlinks/webapi2/organic-traffic', { domain });

      if (!r.ok) {
        return {
          status: 'http_error',
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

      // HTTP 200 without organic_traffic is a legitimate Semrush no-data response, not an API error.
      return {
        status: 'no_data',
        domain,
        http_status: r.httpStatus,
        organic_traffic: null,
        databases: r.data?.databases || null,
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
          status: 'http_error',
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
      throw new Error(`Semrush preflight 失败：${reason}。诊断 JSON 已自动下载。`);
    }

    console.clear();
    console.log(`🚀 BacklinkOS Semrush Runner ${VERSION}`);
    console.log(`Batch: ${config.batchId} | candidates=${config.domains.length} | trafficMin=${config.trafficMin}`);

    // Preflight: verify both real contracts before touching the whole batch.
    const preOrganic = await queryOrganic(config.preflightDomain);
    if (!['value', 'no_data'].includes(preOrganic.status)) {
      failPreflight('organic_contract_failed', preOrganic);
    }
    await sleep(config.delayMs);

    const preRd = await queryRefDomains(config.preflightDomain, 0);
    if (preRd.status !== 'value') {
      failPreflight('refdomains_contract_failed', preRd);
    }

    console.log(`✅ Preflight passed: organic=${preOrganic.status}, RD total=${preRd.total}`);

    const output = {
      batch_id: config.batchId,
      runner_version: VERSION,
      generated_at: new Date().toISOString(),
      settings: {
        traffic_min: config.trafficMin,
        candidate_count: config.domains.length,
        max_rd_rows_per_project: config.maxRdRowsPerProject,
        organic_traffic_semantics: 'global organic traffic',
        country_traffic_semantics: 'response.databases[country]',
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
      errors: [],
      warnings: [],
    };

    // Step 1: Organic Traffic
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
        console.log('  → no_data（HTTP 200；Semrush 未给出 Organic Traffic，不计入 error）');
      } else {
        output.errors.push({ stage: 'organic', domain, ...organic });
        console.warn(`  ❌ ${organic.status}: ${organic.error || ''}`);
      }

      await sleep(config.delayMs);
    }

    const qualifiedProjects = output.projects.filter((p) => p.qualified);
    console.log(`✅ Organic finished: qualified=${qualifiedProjects.length}/${output.projects.length}`);

    // Step 2: Referring Domains, page until complete unless an explicit cap is configured.
    for (let i = 0; i < qualifiedProjects.length; i++) {
      const project = qualifiedProjects[i];
      const merged = new Map();
      let page = 0;
      let reportedTotal = null;
      let limit = 100;
      let stoppedByCap = false;

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

        let added = 0;
        for (const row of rd.rows) {
          const refDomain = normalizeDomain(row?.domain);
          if (!refDomain) continue;
          if (merged.has(refDomain)) continue;

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
            first_seen: row.first_seen ?? null,
            first_seen_iso: toIsoOrNull(row.first_seen),
            last_seen: row.last_seen ?? null,
            last_seen_iso: toIsoOrNull(row.last_seen),
            ip: row.ip ?? null,
            country: row.country ?? '',
            domain_ascore: row.domain_ascore ?? null,
            category: row.category ?? '',
            lost: row.lost ?? false,
            new: row.new ?? false,
            is_follow: row.is_follow ?? null,
          });
          added++;
        }

        project.rd_pages_fetched++;
        console.log(`  page ${page}: ${rd.rows.length} rows, +${added}, total=${reportedTotal}`);

        if (stoppedByCap) break;
        if (merged.size >= reportedTotal) break;
        if (rd.rows.length < limit) break;
        if (added === 0) {
          output.warnings.push({ stage: 'refdomains', domain: project.domain, page, warning: 'no_new_rows_on_page' });
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

    // Aggregate referring domains across successful projects.
    const aggregates = new Map();
    for (const row of output.refdomain_rows) {
      const key = row.referring_domain;
      if (!aggregates.has(key)) {
        aggregates.set(key, {
          referring_domain: key,
          source_projects: new Set(),
          occurrence_count: 0,
          max_as: null,
          follow_count: 0,
          new_link_count: 0,
          earliest_seen: null,
          example_projects: [],
        });
      }
      const a = aggregates.get(key);
      a.source_projects.add(row.source_project);
      a.occurrence_count++;
      if (typeof row.domain_ascore === 'number') a.max_as = a.max_as === null ? row.domain_ascore : Math.max(a.max_as, row.domain_ascore);
      if (row.is_follow === true) a.follow_count++;
      if (row.new === true) a.new_link_count++;
      if (typeof row.first_seen === 'number') a.earliest_seen = a.earliest_seen === null ? row.first_seen : Math.min(a.earliest_seen, row.first_seen);
      if (!a.example_projects.includes(row.source_project) && a.example_projects.length < 5) a.example_projects.push(row.source_project);
    }

    output.refdomain_aggregates = [...aggregates.values()]
      .map((a) => ({
        referring_domain: a.referring_domain,
        successful_project_count: a.source_projects.size,
        occurrence_count: a.occurrence_count,
        max_as: a.max_as,
        follow_count: a.follow_count,
        follow_rate: a.occurrence_count ? a.follow_count / a.occurrence_count : null,
        new_link_count: a.new_link_count,
        earliest_seen: a.earliest_seen,
        earliest_seen_iso: toIsoOrNull(a.earliest_seen),
        example_projects: a.example_projects,
      }))
      .sort((a, b) => b.successful_project_count - a.successful_project_count || b.occurrence_count - a.occurrence_count || (b.max_as || 0) - (a.max_as || 0));

    const statusCounts = output.projects.reduce((acc, p) => {
      acc[p.organic_status] = (acc[p.organic_status] || 0) + 1;
      return acc;
    }, {});

    output.summary = {
      candidate_projects: output.projects.length,
      organic_value: statusCounts.value || 0,
      organic_no_data: statusCounts.no_data || 0,
      organic_http_error: statusCounts.http_error || 0,
      organic_schema_error: statusCounts.schema_error || 0,
      qualified_projects: qualifiedProjects.length,
      raw_refdomain_rows: output.refdomain_rows.length,
      unique_referring_domains: aggregates.size,
      rd_projects_complete: qualifiedProjects.filter((p) => p.rd_complete).length,
      rd_projects_partial: qualifiedProjects.filter((p) => !p.rd_complete).length,
      errors: output.errors.length,
      warnings: output.warnings.length,
    };

    downloadJson(output, `BacklinkOS-${config.batchId}-semrush-${Date.now()}.json`);
    console.log('✅ 全部完成，最终 JSON 已自动下载。');
    console.table(output.summary);
    return output;
  }

  window.runBacklinkOSSemrush = runBacklinkOSSemrush;
  console.log(`✅ BacklinkOS Semrush Runner ${VERSION} loaded.`);
  console.log('调用：runBacklinkOSSemrush({batchId:"B20260821-001", domains:["example.com"], trafficMin:500})');
})();
