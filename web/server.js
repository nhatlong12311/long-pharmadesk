/* The browser holds drafts and settings. Clinical computations are HTTPS requests. */
(() => {
  const nativeFetch = window.fetch.bind(window);
  const storage = import("./adr-storage.mjs?v=__STORAGE_VERSION__");
  const reports = new Map();
  const maxBytes = 4_400_000;
  const watch = "ABCVEN/hoat_chat_theo_doi.json";
  const rules = "TuongTac/Quy_tac_tuong_tac.json";
  const generate = new Set(["/api/abc/generate", "/api/abc/generate-four"]);
  const mime = {
    xlsx:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    docx:"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  };

  function period(month, year) {
    return "ABCVEN/Lich_su/" + year + "-" + String(month).padStart(2, "0") + ".json";
  }

  function previous(month, year) {
    return month === 1 ? [12, year - 1] : [month - 1, year];
  }

  async function history(url, files) {
    const month = Number(url.searchParams.get("month"));
    const year = Number(url.searchParams.get("year"));
    if (!Number.isInteger(month) || !Number.isInteger(year) || month < 1 || month > 12 || year < 2000 || year > 2100) {
      return Response.json({ok:false, msg:"Tháng hoặc năm báo cáo không hợp lệ."}, {status:400});
    }
    const [pm, py] = previous(month, year);
    const prev = period(pm, py);
    const cur = period(month, year);
    const saved = await files.readStateFiles([prev, cur]);
    return Response.json({
      pm, py, prev_has_rows: Boolean(saved[prev]?.rows?.length),
      prev_stats: saved[prev]?.stats ?? {}, cur_stats: saved[cur]?.stats ?? {},
    });
  }

  function packedForm(url, original, body) {
    return new Request(url, {method:"POST", body, signal:original.signal});
  }

  function packedJson(url, original, body) {
    return new Request(url, {
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body), signal:original.signal,
    });
  }

  function fileBlob(data, name) {
    const bytes = Uint8Array.from(atob(data), char => char.charCodeAt(0));
    return new Blob([bytes], {type:mime[name.split(".").at(-1)]});
  }

  async function serverRequest(request, url) {
    const path = url.pathname;
    const files = await storage;
    if (/^\/api\/adr\/(?:state|drafts?|draft\/delete)$/.test(path)) {
      const handled = await files.handleAdrRequest(request.method, url, await request.arrayBuffer());
      if (handled) return handled;
    }
    if (path === "/api/abc/history" && request.method === "GET") return history(url, files);

    let outgoing = request;
    if (request.method === "POST" && (generate.has(path) || path === "/api/ttt/inspect" || path === "/api/ttt/generate")) {
      const form = await request.formData();
      let keys = [rules];
      if (generate.has(path)) {
        const {month, year} = JSON.parse(form.get("opts") ?? "{}");
        keys = [watch, period(Number(month), Number(year)), period(...previous(Number(month), Number(year)))];
      }
      const saved = await files.readStateFiles(keys);
      if (Object.keys(saved).length) {
        form.set("_state", new Blob([JSON.stringify(saved)], {type:"application/json"}), "history.json");
      }
      outgoing = packedForm(url, request, form);
    } else if (path === "/api/abc/watch" && request.method === "POST") {
      outgoing = packedJson(url, request, {...await request.json(), _state:await files.readStateFiles([watch])});
    } else if (path === "/api/ttt/state" && request.method === "GET") {
      const saved = await files.readStateFiles([rules]);
      if (saved[rules]) outgoing = packedJson(url, request, {_state:saved});
    }

    if (outgoing.body && (await outgoing.clone().arrayBuffer()).byteLength > maxBytes) {
      return Response.json({ok:false, msg:"Tổng dung lượng mỗi lượt gửi lên máy chủ tối đa 4,4 MB. Hãy chia nhỏ dữ liệu."}, {status:413});
    }
    const response = await nativeFetch(outgoing);
    if (!response.headers.get("content-type")?.includes("application/json")) {
      const msg = response.status === 413
        ? "Tổng dung lượng mỗi lượt gửi lên máy chủ tối đa 4,4 MB."
        : "Máy chủ Vercel chưa xử lý được yêu cầu. Vui lòng thử lại.";
      return Response.json({ok:false, msg}, {status:response.ok ? 502 : response.status});
    }
    if (!response.ok) return response;
    if (path === "/api/abc/state") {
      const data = await response.json();
      const saved = (await files.readStateFiles([watch]))[watch];
      if (saved?.length) data.watch = saved;
      return Response.json(data);
    }
    if (generate.has(path) || ["/api/abc/watch", "/api/abc/export-month", "/api/abc/compare-month",
      "/api/ttt/rules", "/api/ttt/generate"].includes(path)) {
      const data = await response.json();
      if (data.inline_file && data.name) {
        reports.set(path.split("/")[2] + "/" + data.name, fileBlob(data.inline_file, data.name));
        delete data.inline_file;
      }
      if (data._state) {
        try { await files.writeStateFiles(data._state); }
        catch {
          (data.warnings ??= []).push("Không lưu được lịch sử trên trình duyệt. Hãy tải báo cáo về.");
          data.storage_warning = true;
        }
        delete data._state;
      }
      return Response.json(data);
    }
    return response;
  }

  window.fetch = async (input, options) => {
    const request = new Request(input, options);
    const url = new URL(request.url);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return nativeFetch(request);
    try {
      return await serverRequest(request, url);
    } catch {
      return Response.json({ok:false, msg:"Chưa xử lý được yêu cầu. Hãy kiểm tra kết nối và thử lại."}, {status:503});
    }
  };

  window.pharmaDeskServer = {
    abcFields: __ABC_FIELDS__,
    async download(url, name) {
      const key = new URL(url, location.origin).pathname.split("/")[2] + "/" + name;
      const blob = reports.get(key);
      if (!blob) throw new Error("Không thấy báo cáo trong tab này. Hãy tạo lại báo cáo.");
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    },
  };
})();
