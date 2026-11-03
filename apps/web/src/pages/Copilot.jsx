import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import api from "../services/api";
import { getCurrentUser } from "../services/authService";
import formatRichText from "../utils/formatRichText";
import PromptBar from "../components/common/PromptBar";
import ThemeToggle from "../components/common/ThemeToggle";
import { useTheme } from "../context/ThemeContext";
import {
  Attachment01Icon,
  Globe02Icon,
  ChartLineData01Icon,
  File02Icon,
} from "@hugeicons/core-free-icons";
import "./Copilot.css";

const COPILOT_SOURCES = [
  {
    key: "files",
    name: "Photos & Micrographs",
    description: "Upload micrographs or documents",
    icon: Attachment01Icon,
    attach: true,
  },
  {
    key: "analysis",
    name: "Active Analysis",
    description: "Grain size, phases & defect metrics",
    icon: ChartLineData01Icon,
  },
  {
    key: "standards",
    name: "ASTM / ISO Standards",
    description: "E112 grain specs, E45 inclusion limits",
    icon: File02Icon,
  },
  {
    key: "web",
    name: "Web & Metallurgical Specs",
    description: "Live search & alloy phase databases",
    icon: Globe02Icon,
  },
];

const COPILOT_COMMANDS = [
  {
    key: "explain",
    name: "/explain",
    description: "Plain-language walkthrough of metallurgical findings",
  },
  {
    key: "anomalies",
    name: "/anomalies",
    description: "Detect micro-cracks, inclusions & pores",
  },
  {
    key: "report",
    name: "/report",
    description: "Generate an audit-ready inspection report",
  },
  {
    key: "quality",
    name: "/quality",
    description: "Break down optical quality & focus score",
  },
  {
    key: "summarize",
    name: "/summarize",
    description: "Digest the conversation thread so far",
  },
];

const COPILOT_MODELS = [
  { key: "gemini-1.5-pro", name: "Gemini 1.5 Pro", tag: "Flagship" },
  { key: "gemini-1.5-flash", name: "Gemini Flash", tag: "Fast" },
  { key: "nodiq-core", name: "NODIQ Metallurgy Engine", tag: "Deterministic" },
];

/* The history sidebar starts with just the live conversation; entries are
   added as the user actually creates chats in this session. */
const initialChats = [
  {
    id: 1,
    title: "Current conversation",
    group: "Today",
  },
];

const suggestedQuestions = [
  {
    icon: "description",
    title: "Explain this analysis",
    text: "Explain this analysis — what are the main findings?",
  },
  {
    icon: "help",
    title: "Why is quality low?",
    text: "Why is the image quality at its current level? Explain using the real quality metrics.",
  },
  {
    icon: "warning",
    title: "Check anomalies",
    text: "Are there any anomalies or concerns before approval?",
  },
  {
    icon: "description",
    title: "Generate report",
    text: "Generate a report for this analysis.",
  },
];

function providerStatusLabel(status) {
  const state = status?.state || "NOT_CONFIGURED";
  const provider = (status?.active_provider || "").toLowerCase();
  if (state === "ONLINE") {
    const name = provider === "gemini" ? "Gemini"
      : provider === "openai" ? "OpenAI-compatible"
        : provider === "local" ? "Local LLM" : provider || "LLM";
    return `Online — ${name}`;
  }
  if (state === "ERROR") return "Offline — provider error";
  if (state === "OFFLINE") return "Offline — NODIQ-X Engine";
  return "Offline — NODIQ-X Engine";
}

function Icon({ name, className = "" }) {
  return (
    <span className={`material-symbols-outlined ${className}`}>
      {name}
    </span>
  );
}

function getCurrentUserName() {
  /* Prefer the live authenticated session (authService); the legacy local
     "registered users" store is only a fallback for old local accounts. */
  try {
    const session = getCurrentUser();
    if (session?.name) return session.name;
  } catch {
    /* fall through */
  }

  try {
    const remembered = JSON.parse(localStorage.getItem("nodiq_user_credentials") || "null");
    const registeredUsers = JSON.parse(localStorage.getItem("nodiq_registered_users") || "[]");

    if (remembered?.email) {
      const matchedUser = registeredUsers.find(
        (user) => String(user.email).toLowerCase() === String(remembered.email).toLowerCase()
      );

      if (matchedUser?.name) {
        return matchedUser.name;
      }
    }

    if (remembered?.email) {
      return remembered.email.split("@")[0];
    }
  } catch {
    // Ignore storage issues and fall back to a friendly default.
  }

  return "there";
}

function splitProviderNotice(content) {
  const match = String(content || {}).match(/\s*_\((?:The online AI provider|Answered by the offline)[\s\S]*?\)_\s*$/i);
  if (!match) return { content, notice: "" };
  return { content: String(content).slice(0, match.index).trim(), notice: match[0].trim().slice(2, -2) };
}

function Copilot() {
  const navigate = useNavigate();
  const location = useLocation();
  const userName = getCurrentUserName();
  const { theme } = useTheme();

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [chatHistoryOpen, setChatHistoryOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [chats, setChats] = useState(initialChats);
  const [activeChat, setActiveChat] = useState(1);
  const [menuChatId, setMenuChatId] = useState(null);

  const textareaRef = useRef(null);
  const messagesRef = useRef(null);
  const seedSentRef = useRef(false);
  const sendMessageRef = useRef(null);

  // Stable per-browser session id so the backend keeps conversation memory
  // across turns (logic-only; no visual change).
  const [sessionId] = useState(() => {
    try {
      let sid = localStorage.getItem("nodiq_copilot_session");
      if (!sid) {
        sid = `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
        localStorage.setItem("nodiq_copilot_session", sid);
      }
      return sid;
    } catch {
      return "default";
    }
  });

  /* ---- truthful provider status (Online — Gemini / Offline — Rules) ---- */
  const [providerStatus, setProviderStatus] = useState(null);
  const loadProviderStatus = useCallback(() => {
    api.aiStatus()
      .then((s) => setProviderStatus(s))
      .catch(() => setProviderStatus(null));
  }, []);

  /* ---- real active analysis context (follows the sample being viewed) ---- */
  const [activeAnalysisId, setActiveAnalysisId] = useState(
    () => location.state?.analysisId || ""
  );
  const [contextAnalysis, setContextAnalysis] = useState(null);
  const [drawerImageUrl, setDrawerImageUrl] = useState(null);

  const fetchActiveAnalysis = useCallback(() => {
    api.analyses()
      .then((data) => {
        const rows = data.analyses || [];
        if (!rows.length) return;
        let stored = "";
        try {
          stored = localStorage.getItem("nodiq_active_analysis") || "";
        } catch {
          /* ignore */
        }
        const requested = location.state?.analysisId || "";
        const active = rows.find((r) => r.id === requested) ||
          rows.find((r) => r.id === stored) || rows[0];
        setContextAnalysis(active);
        setActiveAnalysisId(active.id);
        try {
          localStorage.setItem("nodiq_active_analysis", active.id);
        } catch {
          /* ignore */
        }
      })
      .catch(() => {});
  }, [location.state?.analysisId]);

  useEffect(() => {
    loadProviderStatus();
    fetchActiveAnalysis();
  }, [loadProviderStatus, fetchActiveAnalysis]);

  /* "Explain this report" / deep links arrive with a seed message — send it
     once on mount so the Copilot immediately works on the right context. */
  useEffect(() => {
    if (seedSentRef.current) return;
    const seed = location.state?.seedMessage;
    if (seed) {
      seedSentRef.current = true;
      navigate(location.pathname, { replace: true, state: null });
      sendMessageRef.current?.(seed);
    }
  }, [location.state, location.pathname, navigate]);

  /* Micrograph preview for the context drawer (authenticated blob). */
  useEffect(() => {
    if (!contextOpen || !contextAnalysis?.id) {
      setDrawerImageUrl(null);
      return undefined;
    }
    let revoked = false;
    api.fetchImage(api.analysisImageUrl(contextAnalysis.id))
      .then((u) => {
        if (revoked) URL.revokeObjectURL(u);
        else setDrawerImageUrl(u);
      })
      .catch(() => {});
    return () => {
      revoked = true;
      setDrawerImageUrl(null);
    };
  }, [contextOpen, contextAnalysis?.id]);

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [messages, isThinking]);

  const filteredChats = chats.filter((chat) =>
    chat.title.toLowerCase().includes(search.toLowerCase())
  );

  const groupedChats = {
    Today: filteredChats.filter((chat) => chat.group === "Today"),
    Yesterday: filteredChats.filter((chat) => chat.group === "Yesterday"),
    "Previous 7 days": filteredChats.filter(
      (chat) => chat.group === "Previous 7 days"
    ),
    Older: filteredChats.filter((chat) => chat.group === "Older"),
  };



  const sendMessage = async (message = input) => {
    const trimmedMessage = message.trim();

    if (!trimmedMessage || isThinking) return;

    setMessages((previous) => [
      ...previous,
      {
        id: Date.now(),
        role: "user",
        content: trimmedMessage,
      },
    ]);

    setInput("");

    if (textareaRef.current) {
      textareaRef.current.style.height = "80px";
    }

    setIsThinking(true);

    // Send recent conversation for real multi-turn context (backend builds
    // its own memory too; history here makes provider handoffs seamless).
    const recentHistory = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.content }));

    api.copilot(trimmedMessage, recentHistory, sessionId, {
      current_analysis_id: activeAnalysisId || undefined,
      current_page: "copilot",
    })
      .then((data) => {
        // Strip any un-executed ```action``` blocks defensively; the backend
        // already extracts safe ui_actions for the frontend.
        const cleanReply = (data.reply || "(empty response)")
          .replace(/```action[\s\S]*?```/g, "")
          .trim();
        const actions = (Array.isArray(data.ui_actions) ? data.ui_actions : [])
          .filter((a) => a &&
            (a.action === "generate_report" || a.action === "open_analysis"));
        const answer = splitProviderNotice(cleanReply);
        setMessages((previous) => [
          ...previous,
          {
            id: Date.now() + 1,
            role: "assistant",
            content: answer.content,
            providerNotice: answer.notice,
            actions,
            provider: data.provider,
          },
        ]);
        loadProviderStatus();          // keep the Online/Offline chip truthful
        if (actions.length > 0) fetchActiveAnalysis();
      })
      .catch((e) => {
        setMessages((previous) => [
          ...previous,
          {
            id: Date.now() + 1,
            role: "assistant",
            content:
              "I could not reach the analysis backend. Is server.py running? (" +
              (e.message || "connection error") +
              ")",
          },
        ]);
      })
      .finally(() => {
        setIsThinking(false);
      });
  };

  sendMessageRef.current = sendMessage;

  const handlePromptSend = (text, { attachments = [], effort } = {}) => {
    let fullText = text.trim();
    if (attachments && attachments.length > 0) {
      fullText += `\n\n[Attached: ${attachments.join(", ")}]`;
    }
    if (effort && effort !== "Medium") {
      fullText += `\n(Reasoning Effort: ${effort})`;
    }
    sendMessage(fullText);
  };

  const handlePromptAttach = () => {
    return new Promise((resolve) => {
      const fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.accept = "image/*,.png,.jpg,.jpeg,.tif,.tiff,.pdf,.csv,.json";
      fileInput.multiple = true;
      fileInput.onchange = () => {
        const fileNames = Array.from(fileInput.files || []).map((f) => f.name);
        resolve(fileNames);
      };
      fileInput.oncancel = () => resolve([]);
      fileInput.click();
    });
  };

  const handlePromptDictate = () => {
    return new Promise((resolve) => {
      const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRec) {
        alert("Speech recognition is not supported in this browser.");
        resolve("");
        return;
      }
      try {
        const recognition = new SpeechRec();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = "en-US";
        recognition.onresult = (event) => {
          const transcript = event.results[0]?.[0]?.transcript || "";
          resolve(transcript);
        };
        recognition.onerror = () => resolve("");
        recognition.onend = () => resolve("");
        recognition.start();
      } catch {
        resolve("");
      }
    });
  };

  const resetConversation = () => {
    setInput("");
    setMessages([]);
    setIsThinking(false);
    setActiveChat(1);
    setSearch("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "80px";
    }
  };

  const createNewChat = () => {
    const newChat = {
      id: Date.now(),
      title: "New Copilot conversation",
      group: "Today",
    };

    setChats((previous) => [newChat, ...previous]);
    setActiveChat(newChat.id);

    setMessages([]);
  };

  const handleSuggestedQuestion = (question) => {
    sendMessage(question);
  };

  const handleDeleteChat = (chatId) => {
    setChats((previous) => {
      const remainingChats = previous.filter((chat) => chat.id !== chatId);

      if (remainingChats.length === 0) {
        setActiveChat(null);
        setMessages([]);
        setInput("");
        setIsThinking(false);
        return [];
      }

      const nextActiveChat = remainingChats[0].id;
      setActiveChat(nextActiveChat);
      setMessages([]);
      setInput("");
      setIsThinking(false);
      return remainingChats;
    });

    setMenuChatId(null);
  };

  const handleCopy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard permissions may be unavailable.
    }
  };

  const handleExport = () => {
    if (messages.length === 0) {
      window.alert("Nothing to export yet — start a conversation first.");
      return;
    }
    const text = messages
      .map((m) => `[${m.role === "user" ? "You" : "NODIQ Copilot"}] ${m.content}`)
      .join("\n\n");
    const blob = new Blob([`NODIQ-X Copilot conversation\n\n${text}\n`], {
      type: "text/plain",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nodiq-copilot-${Date.now()}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleNotifications = async () => {
    try {
      const data = await api.analyses();
      const flagged = (data.analyses || []).filter(
        (a) => (a.warnings || []).length > 0 ||
          (typeof a.accuracy_pct === "number" && a.accuracy_pct < 95),
      );
      window.alert(
        flagged.length === 0
          ? "No alerts — every recent analysis passed the 95% self-check gate."
          : `${flagged.length} analysis run(s) need review:\n\n` +
            flagged.slice(0, 5).map((a) => `• ${a.id} — ${a.filename || "upload"}`).join("\n"),
      );
    } catch {
      window.alert("Could not reach the analysis backend.");
    }
  };


  const handleRegenerate = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    setMessages((previous) => {
      const idx = previous.map((m) => m.role).lastIndexOf("assistant");
      return idx === -1 ? previous : previous.filter((_, i) => i !== idx);
    });
    sendMessage(lastUser.content);
  };

  return (
    <div className="copilot-page">
      {/* =========================================
          COPILOT HEADER
      ========================================= */}
      <header className="copilot-header">
        <div className="copilot-header-left">
          <div className="copilot-brand">
            <span>NODIQ-X</span>
          </div>

          <div className="copilot-header-divider" />

          <div className="copilot-title">
            <Icon name="smart_toy" />
            <span>NODIQ Copilot</span>
          </div>
        </div>

        <div className="copilot-header-actions">
          <button
            className="analysis-context-pill"
            onClick={() => setContextOpen(true)}
            type="button"
          >
            <span className="context-status-dot" />
            <span>
              {contextAnalysis?.id || "No analysis"} <span>• Analysis Context</span>
            </span>
            <Icon name="keyboard_arrow_down" />
          </button>

          <div
            className={`copilot-provider-status provider-${(providerStatus?.state || "NOT_CONFIGURED").toLowerCase()}`}
            title={providerStatus?.state_detail || ""}
          >
            <span className="provider-dot" />
            <span>{providerStatusLabel(providerStatus)}</span>
          </div>

          <div className="header-divider" />

          <button
            className="header-icon-button"
            type="button"
            onClick={() => setChatHistoryOpen((open) => !open)}
            aria-label="Toggle chat history"
            title="Toggle chat history"
          >
            <Icon name="menu" />
          </button>

          <button
            className="header-icon-button"
            type="button"
            onClick={resetConversation}
            aria-label="Reset conversation"
            title="Reset conversation"
          >
            <Icon name="history" />
          </button>

          <button className="header-icon-button" type="button" onClick={handleNotifications} title="Alerts">
            <Icon name="notifications" />
          </button>

          <ThemeToggle className="copilot-theme-toggle" />

          <button className="export-button" type="button" onClick={handleExport}>
            Export
          </button>

          <button
            className="new-analysis-button"
            onClick={() => navigate("/new-analysis")}
            type="button"
          >
            <span>+</span>
            New Analysis
          </button>

          <div className="user-avatar">
            <span>{(userName || "G").charAt(0).toUpperCase()}</span>
          </div>
        </div>
      </header>

      {/* =========================================
          COPILOT BODY
      ========================================= */}
      <div className="copilot-body">
        {/* =====================================
            CHAT HISTORY
        ===================================== */}
        <aside className={`chat-history ${chatHistoryOpen ? "" : "chat-history-hidden"}`}>
          <div className="chat-history-create">
            <button
              className="new-chat-button"
              onClick={createNewChat}
              type="button"
            >
              <Icon name="add" />
              <span>New Chat</span>
            </button>
          </div>

          <div className="chat-search">
            <div className="chat-search-wrapper">
              <Icon name="search" />
              <input
                type="text"
                placeholder="Search history..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </div>

          <div className="chat-history-list">
            {Object.entries(groupedChats).map(([group, groupChats]) => {
              if (groupChats.length === 0) return null;

              return (
                <div className="history-group" key={group}>
                  <div className="history-group-title">{group}</div>

                  {groupChats.map((chat) => (
                    <div key={chat.id} className="history-chat-wrapper">
                      <button
                        type="button"
                        className={`history-chat ${
                          activeChat === chat.id ? "active" : ""
                        }`}
                        onClick={() => setActiveChat(chat.id)}
                      >
                        <span>{chat.title}</span>
                      </button>

                      {activeChat === chat.id && (
                        <div className="chat-menu-container">
                          <button
                            type="button"
                            className="chat-menu-button"
                            aria-label="Chat options"
                            onClick={(event) => {
                              event.stopPropagation();
                              setMenuChatId((current) =>
                                current === chat.id ? null : chat.id
                              );
                            }}
                          >
                            <Icon name="more_vert" />
                          </button>

                          {menuChatId === chat.id && (
                            <div className="chat-menu-popup">
                              <button
                                type="button"
                                className="chat-menu-item"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleDeleteChat(chat.id);
                                }}
                              >
                                <Icon name="delete" />
                                Delete chat
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </aside>

        {/* =====================================
            MAIN CHAT
        ===================================== */}
        <main className="copilot-main">
          <div className="messages-container" ref={messagesRef}>
            {messages.length === 0 ? (
              <div className="copilot-empty-state">
                <div className="copilot-ai-icon">
                  <Icon name="smart_toy" />
                </div>

                <h1>Hello{userName === "there" ? " there" : `, ${userName}`}</h1>

                <p>
                  Your AI assistant for metallographic analysis and
                  microstructure understanding.
                </p>

                <div className="suggested-questions">
                  {suggestedQuestions.map((question) => (
                    <button
                      key={question.title}
                      type="button"
                      className="suggested-question"
                      onClick={() => handleSuggestedQuestion(question.text)}
                    >
                      <div className="suggested-icon">
                        <Icon name={question.icon} />
                      </div>

                      <div>
                        <strong>{question.title}</strong>
                        <span>{question.text}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="conversation">
                {messages.map((message) => (
                  <div
                    className={`message-row ${
                      message.role === "user"
                        ? "message-user"
                        : "message-assistant"
                    }`}
                    key={message.id}
                  >
                    {message.role === "assistant" && (
                      <div className="assistant-avatar">
                        <Icon name="smart_toy" />
                      </div>
                    )}

                    <div className="message-content">
                      {message.role === "assistant" && (
                        <div className="assistant-label">
                          NODIQ Copilot
                          <span>•</span>
                          Just now
                        </div>
                      )}

                      {message.role === "user" ? (
                        <div className="user-message-bubble">
                          {message.content}
                        </div>
                      ) : message.actions?.length ? (
                        <AssistantActionMessage
                          message={message}
                          onNavigate={navigate}
                        />
                      ) : (
                        <div className="assistant-response">
                          <div className="assistant-rich">
                            {formatRichText(message.content, "m")}
                          </div>
                          {message.providerNotice && (
                            <div className="provider-notice">
                              <Icon name="info" />
                              <span>{message.providerNotice}</span>
                            </div>
                          )}
                        </div>
                      )}

                      {message.role === "assistant" && (
                        <div className="message-actions">
                          <button
                            type="button"
                            onClick={() => handleCopy(message.content)}
                          >
                            <Icon name="content_copy" />
                            Copy
                          </button>

                          <button type="button">
                            <Icon name="thumb_up" />
                            Helpful
                          </button>

                          <button type="button">
                            <Icon name="thumb_down" />
                          </button>

                          <button type="button" onClick={handleRegenerate}>
                            <Icon name="refresh" />
                            Regenerate
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {isThinking && (
                  <div className="message-row message-assistant">
                    <div className="assistant-avatar thinking-avatar">
                      <Icon name="smart_toy" />
                    </div>

                    <div className="message-content">
                      <div className="assistant-label">
                        NODIQ Copilot
                        <span>•</span>
                        Thinking
                      </div>

                      <div className="thinking-indicator">
                        <span />
                        <span />
                        <span />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* =================================
              INPUT
          ================================= */}
          <div className="copilot-input-area">
            <PromptBar
              placeholder="Ask NODIQ Copilot... (type @ for sources, / for commands)"
              sources={COPILOT_SOURCES}
              commands={COPILOT_COMMANDS}
              models={COPILOT_MODELS}
              efforts={["Low", "Medium", "High", "Extra", "Max"]}
              defaultEffort="Medium"
              busy={isThinking}
              onSend={handlePromptSend}
              onStop={() => setIsThinking(false)}
              onAttach={handlePromptAttach}
              onDictate={handlePromptDictate}
              sparkColor={theme === "light" ? "#ea580c" : "#ff7a18"}
              sparkBoost={1}
              width={900}
              radius={14}
              maxRows={6}
              morphDuration={240}
              squash={0.12}
              tilt={8}
              pressScale={0.96}
            />

            <div className="ai-disclaimer">
              AI can make mistakes. Verify critical metallurgical measurements.
            </div>
          </div>
        </main>

        {/* =====================================
            ANALYSIS CONTEXT DRAWER
        ===================================== */}
        {contextOpen && (
          <aside className="analysis-context">
            <div className="context-header">
              <div>
                <span>Current Context</span>
                <strong>{contextAnalysis?.id || "No analysis"}</strong>
              </div>

              <button
                type="button"
                onClick={() => setContextOpen(false)}
              >
                <Icon name="close" />
              </button>
            </div>

            <div className="context-content">
              <div className="context-status">
                <span>Analysis</span>

                {contextAnalysis ? (
                  <span className="active-badge">
                    <span />
                    {contextAnalysis.filename || "Measured"}
                  </span>
                ) : (
                  <span className="active-badge active-badge--empty">
                    <span />
                    No analysis loaded
                  </span>
                )}
              </div>

              <div className="microstructure-preview">
                {drawerImageUrl ? (
                  <img
                    className="context-image"
                    src={drawerImageUrl}
                    alt="Active analysis micrograph"
                  />
                ) : (
                  <div className="microstructure-placeholder">
                    <div className="microstructure-grid" />
                    <span>
                      {contextAnalysis ? "MICROSTRUCTURE" : "NO ANALYSIS IN CONTEXT"}
                    </span>
                  </div>
                )}
              </div>

              {contextAnalysis && (
                <>
                  <div className="metrics-section">
                    <div className="section-label">Key Metrics</div>

                    <div className="metrics-grid">
                      <Metric
                        label="ISO NODULARITY"
                        value={contextAnalysis.iso_nodularity_pct ?? "—"}
                        unit="%"
                      />

                      <Metric
                        label="JIS NODULARITY"
                        value={contextAnalysis.jis_nodularity_pct ?? "—"}
                        unit="%"
                      />

                      <Metric
                        label="PARTICLE COUNT"
                        value={contextAnalysis.nodule_count ?? "—"}
                      />

                      <Metric
                        label="SELF-CHECK F1"
                        value={contextAnalysis.confidence_pct ?? "—"}
                        unit="%"
                      />
                    </div>
                  </div>

                  <div className="context-extra">
                    <div>
                      <span>Image Quality</span>
                      <strong>{contextAnalysis.quality_score ?? "—"}</strong>
                    </div>

                    <div>
                      <span>Status</span>
                      <strong>{contextAnalysis.status || "completed"}</strong>
                    </div>
                  </div>
                </>
              )}

              <div className="context-action">
                <button
                  type="button"
                  onClick={() => navigate("/new-analysis")}
                >
                  <Icon name="open_in_new" />
                  View Full Analysis
                </button>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

/* Assistant reply that carries safe UI actions from the backend tool calls
   (e.g. generate_report -> open the real stored report). */
function AssistantActionMessage({ message, onNavigate }) {
  return (
    <div className="assistant-response">
      <div className="assistant-rich">{formatRichText(message.content, "a")}</div>

      {(message.actions || []).map((a, i) => {
        if (a.action === "generate_report" && a.report_id) {
          return (
            <button
              key={i}
              type="button"
              className="copilot-action-card"
              onClick={() => onNavigate(`/reports/${a.report_id}`)}
            >
              <span className="material-symbols-outlined">description</span>
              <span className="copilot-action-text">
                <strong>Report generated</strong>
                <span>Open {a.report_id} in the report viewer</span>
              </span>
              <span className="material-symbols-outlined">arrow_forward</span>
            </button>
          );
        }

        if (a.action === "open_analysis" && a.analysis_id) {
          return (
            <button
              key={i}
              type="button"
              className="copilot-action-card"
              onClick={() => {
                try {
                  localStorage.setItem("nodiq_active_analysis", a.analysis_id);
                } catch {
                  /* ignore */
                }
                onNavigate("/new-analysis");
              }}
            >
              <span className="material-symbols-outlined">science</span>
              <span className="copilot-action-text">
                <strong>Analysis ready</strong>
                <span>Open {a.analysis_id}</span>
              </span>
              <span className="material-symbols-outlined">arrow_forward</span>
            </button>
          );
        }

        return null;
      })}
    </div>
  );
}

function Metric({ label, value, unit }) {
  return (
    <div className="metric-card">
      <span>{label}</span>

      <strong>
        {value}

        {unit && <small>{unit}</small>}
      </strong>
    </div>
  );
}

export default Copilot;