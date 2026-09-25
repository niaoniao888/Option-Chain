"use strict";
(() => {
  const apiPath=path=>{const pathname=globalThis.location?.pathname||"",index=pathname.lastIndexOf("/bitcoin/");return `${index<0?"":pathname.slice(0,index)}${path}`;};
  const REQUEST_TIMEOUT_MS = 8000;
  const view = document.getElementById("guideView");
  if (!view) return;

  const editable = view.dataset.guideMode === "editor";
  const nodes = {
    meta: document.getElementById("guideMeta"),
    message: document.getElementById("guideMessage"),
    content: document.getElementById("guideContent"),
    editor: document.getElementById("guideEditor"),
    edit: document.getElementById("guideEdit"),
    refresh: document.getElementById("guideRefresh"),
    cancel: document.getElementById("guideCancel"),
    save: document.getElementById("guideSave"),
    editActions: document.getElementById("guideEditActions"),
  };
  const state = {document: null, draft: null, loading: false, saving: false, editing: false};
  let rememberedTopic = "";
  if (!editable) {try {const saved=localStorage.getItem("btc-options-mobile-guide-topic");if(typeof saved==="string"&&saved.length<1000)rememberedTopic=saved;} catch (_) {}}
  const rememberTopic = key => {if(editable)return;rememberedTopic=key;try{localStorage.setItem("btc-options-mobile-guide-topic",key);}catch(_){}};
  let topicSequence = 0;
  const clear = node => { while (node?.firstChild) node.removeChild(node.firstChild); };
  const button = (label, className = "") => {
    const node = document.createElement("button");
    node.type = "button";
    node.textContent = label;
    if (className) node.className = className;
    return node;
  };
  const setMessage = (text, tone = "") => {
    nodes.message.textContent = text;
    nodes.message.className = `guide-message${tone ? ` ${tone}` : ""}`;
  };
  const updatedText = value => {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "时间未知";
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
      timeZone:"Asia/Shanghai", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false,
    }).formatToParts(date).filter(part => part.type !== "literal").map(part => [part.type, part.value]));
    return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  };
  const cloneSections = sections => sections.map(section => ({
    id: String(section.id || ""), title: String(section.title || ""),
    topics: Array.isArray(section.topics) ? section.topics.map(topic => ({id:String(topic.id || ""), title:String(topic.title || ""), body:String(topic.body || "")})) : [],
  }));
  const timeoutError = () => Object.assign(new Error("请求超时，请稍后重试"), {code:"REQUEST_TIMEOUT"});
  async function requestGuide(options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(apiPath("/api/options-guide"), {...options, signal:controller.signal});
      let payload;
      try { payload = await response.json(); }
      catch (error) {
        if (controller.signal.aborted) throw timeoutError();
        if (!response.ok) throw Object.assign(new Error(`HTTP ${response.status}`), {status:response.status});
        throw error;
      }
      if (!response.ok) {
        const message = payload && typeof payload.error === "string" && payload.error.trim() ? payload.error.trim() : `HTTP ${response.status}`;
        throw Object.assign(new Error(message), {status:response.status});
      }
      return payload;
    } catch (error) {
      if (controller.signal.aborted || error?.name === "AbortError") throw timeoutError();
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  function renderDocument() {
    clear(nodes.content);
    const guide = state.document;
    if (!guide) return;
    nodes.meta.textContent = `更新于 ${updatedText(guide.updated_at)}`;
    guide.sections.forEach(section => {
      const group = document.createElement("section");
      group.className = "guide-section";
      const heading = document.createElement("h3");
      heading.textContent = section.title;
      group.appendChild(heading);
      section.topics.forEach(topic => {
        const detail = document.createElement("details");
        detail.className = "guide-topic";
        detail.setAttribute("name", "options-guide-topic");
        const topicKey=JSON.stringify([section.id,topic.id]);
        if(!editable&&topicKey===rememberedTopic)detail.open=true;
        detail.addEventListener("toggle", () => {
          if(!nodes.content.contains(detail))return;
          if (!detail.open) {if(!editable&&rememberedTopic===topicKey)rememberTopic("");return;}
          rememberTopic(topicKey);
          nodes.content.querySelectorAll("details[open]").forEach(other => {
            if (other !== detail) other.open = false;
          });
        });
        const summary = document.createElement("summary");
        summary.textContent = topic.title;
        const body = document.createElement("p");
        body.textContent = topic.body;
        detail.append(summary, body);
        group.appendChild(detail);
      });
      nodes.content.appendChild(group);
    });
  }

  function topicEditor(topic, sectionIndex, topicIndex) {
    const row = document.createElement("div");
    row.className = "guide-topic-editor";
    const title = document.createElement("input");
    title.type = "text";
    title.value = topic.title;
    title.placeholder = "条目标题";
    title.maxLength = 100;
    title.setAttribute("aria-label", "条目标题");
    title.addEventListener("input", () => { state.draft[sectionIndex].topics[topicIndex].title = title.value; });
    const body = document.createElement("textarea");
    body.value = topic.body;
    body.placeholder = "条目正文（纯文本，可换行）";
    body.rows = 6;
    body.maxLength = 6000;
    body.setAttribute("aria-label", `${topic.title || "新条目"}正文`);
    body.addEventListener("input", () => { state.draft[sectionIndex].topics[topicIndex].body = body.value; });
    const remove = button("删除条目", "danger");
    remove.disabled = state.draft[sectionIndex].topics.length <= 1;
    if (remove.disabled) remove.title = "每个分类至少保留一个条目";
    remove.addEventListener("click", () => { state.draft[sectionIndex].topics.splice(topicIndex, 1); renderEditor(); });
    row.append(title, body, remove);
    return row;
  }

  function renderEditor() {
    if (!editable || !state.draft) return;
    clear(nodes.editor);
    state.draft.forEach((section, sectionIndex) => {
      const group = document.createElement("section");
      group.className = "guide-edit-section";
      const heading = document.createElement("h3");
      heading.textContent = section.title;
      group.appendChild(heading);
      section.topics.forEach((topic, topicIndex) => group.appendChild(topicEditor(topic, sectionIndex, topicIndex)));
      const add = button("新增条目", "secondary");
      const totalTopics = state.draft.reduce((total, item) => total + item.topics.length, 0);
      add.disabled = section.topics.length >= 60 || totalTopics >= 300;
      if (add.disabled) add.title = "条目数量已达到上限";
      add.addEventListener("click", () => {
        topicSequence += 1;
        section.topics.push({id:`topic-${Date.now()}-${topicSequence}`, title:"", body:""});
        renderEditor();
        const inputs = nodes.editor.querySelectorAll(".guide-edit-section")[sectionIndex]?.querySelectorAll("input") || [];
        inputs[inputs.length - 1]?.focus();
      });
      group.appendChild(add);
      nodes.editor.appendChild(group);
    });
  }

  function setEditing(enabled) {
    state.editing = enabled;
    nodes.content.classList.toggle("hidden", enabled);
    nodes.editor?.classList.toggle("hidden", !enabled);
    nodes.editActions?.classList.toggle("hidden", !enabled);
    if (nodes.edit) {
      nodes.edit.classList.toggle("hidden", enabled);
      nodes.edit.disabled = state.loading || !state.document;
    }
    nodes.save?.classList.toggle("hidden", !enabled);
    if (nodes.refresh) nodes.refresh.disabled = state.loading || state.saving || enabled;
    if (enabled) {
      state.draft = cloneSections(state.document.sections);
      renderEditor();
      setMessage("正在编辑。分类固定，可新增、修改或删除条目。", "info");
    } else {
      state.draft = null;
      clear(nodes.editor);
    }
  }

  async function loadGuide() {
    if (state.loading || state.saving || state.editing) return;
    state.loading = true;
    if (nodes.refresh) nodes.refresh.disabled = true;
    if (nodes.edit) nodes.edit.disabled = true;
    setMessage("正在读取期权说明……", "info");
    try {
      const guide = await requestGuide({cache:"no-store"});
      if (!guide || !Array.isArray(guide.sections) || typeof guide.revision !== "string") throw new Error("返回格式无效");
      state.document = {...guide, sections:cloneSections(guide.sections)};
      renderDocument();
      setMessage("");
    } catch (error) {
      setMessage(`读取失败：${error.message}`, "error");
    } finally {
      state.loading = false;
      if (nodes.refresh) nodes.refresh.disabled = false;
      if (nodes.edit) nodes.edit.disabled = !state.document;
    }
  }

  async function saveGuide() {
    if (!editable || state.saving || !state.document || !state.draft) return;
    const invalid = state.draft.some(section => section.topics.some(topic => !topic.title.trim() || !topic.body.trim()));
    if (invalid) { setMessage("每个条目都必须填写标题和正文。", "error"); return; }
    const sections = cloneSections(state.draft).map(section => ({...section, topics:section.topics.map(topic => ({...topic, title:topic.title.trim(), body:topic.body.trim()}))}));
    state.saving = true;
    nodes.save.disabled = true;
    nodes.cancel.disabled = true;
    setMessage("正在保存到本机文件……", "info");
    try {
      const guide = await requestGuide({
        method:"PUT",
        headers:{"Content-Type":"application/json", "If-Match":state.document.revision},
        body:JSON.stringify({sections}),
      });
      if (!guide || !Array.isArray(guide.sections) || typeof guide.revision !== "string") throw new Error("返回格式无效");
      state.document = {...guide, sections:cloneSections(guide.sections)};
      setEditing(false);
      renderDocument();
      setMessage("已保存到本机文件。", "success");
    } catch (error) {
      const message = error?.status === 409
        ? "保存冲突：说明已被其他页面更新，草稿已保留。请另开本机页面读取最新版本，在新页面合并需要保留的修改后保存；不要刷新当前编辑页。"
        : error?.code === "REQUEST_TIMEOUT"
          ? "保存结果尚未确认，草稿已保留。请另开本机页面核对已保存内容，不要刷新当前编辑页。"
          : `保存失败：${error.message}`;
      setMessage(message, "error");
    } finally {
      state.saving = false;
      nodes.save.disabled = false;
      nodes.cancel.disabled = false;
      if (!state.editing) {
        if (nodes.refresh) nodes.refresh.disabled = false;
        nodes.edit.disabled = !state.document;
      }
    }
  }

  nodes.refresh?.addEventListener("click", loadGuide);
  nodes.edit?.addEventListener("click", () => setEditing(true));
  nodes.cancel?.addEventListener("click", () => { setEditing(false); renderDocument(); setMessage("已取消未保存的修改。", "info"); });
  nodes.save?.addEventListener("click", saveGuide);
  window.addEventListener("online", () => { if (!state.document && !state.editing && !view.classList.contains("hidden")) loadGuide(); });
  window.OptionsGuide = {activate:loadGuide};
})();


