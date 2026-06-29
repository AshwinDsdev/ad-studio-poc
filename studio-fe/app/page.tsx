"use client";

import { useState, useRef } from "react";
import dynamic from "next/dynamic";
import ThemeToggle from "./components/ThemeToggle";

const VideoEditor = dynamic(() => import("./components/VideoEditor"), { ssr: false });

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface SceneData {
  scene_number: number;
  image_url: string;
  voice_data: { audio_url: string; words: { word: string; start: number; duration: number }[] };
  text_overlay: string;
  duration_seconds: number;
}

interface Variant {
  variant_index: number;
  variant_label: string;
  hook: string;
  creative_score: number;
  score_rationale: string;
  call_to_action: string;
  video_url: string;
  video_source?: Record<string, any>;
  render_error?: string;
  scenes: SceneData[];
  brand_kit: { logo_url: string; primary_color: string; hero_images: string[] };
  primary_color: string;
  brand_name: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const BACKEND =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

function scoreColor(score: number) {
  if (score >= 75) return "high";
  if (score >= 60) return "medium";
  return "low";
}

function formatLabel(fmt: string) {
  const map: Record<string, string> = { "16:9": "Landscape", "9:16": "Vertical", "1:1": "Square" };
  return map[fmt] ?? fmt;
}

function ratioClass(fmt: string) {
  const map: Record<string, string> = { "16:9": "ratio-16-9", "9:16": "ratio-9-16", "1:1": "ratio-1-1" };
  return map[fmt] ?? "ratio-16-9";
}

// ---------------------------------------------------------------------------
// Variant Card
// ---------------------------------------------------------------------------
function VariantCard({
  variant,
  jobId,
  isTop,
}: {
  variant: Variant;
  jobId: string;
  isTop: boolean;
}) {
  const [activeFormat, setActiveFormat] = useState("16:9");
  const [videoUrl, setVideoUrl] = useState(variant.video_url);
  const [formatLoading, setFormatLoading] = useState(false);
  const [showEditor, setShowEditor] = useState(false);
  const [showAdvancedEditor, setShowAdvancedEditor] = useState(false);
  const [scenes, setScenes] = useState<SceneData[]>(variant.scenes);
  const [rerendering, setRerendering] = useState(false);
  const [renderError, setRenderError] = useState(variant.render_error ?? "");
  const videoRef = useRef<HTMLVideoElement>(null);

  const handleFormatSwitch = async (fmt: string) => {
    if (fmt === activeFormat || formatLoading) return;
    setActiveFormat(fmt);
    if (fmt === "16:9") {
      setVideoUrl(variant.video_url);
      setRenderError(variant.render_error ?? "");
      return;
    }
    setFormatLoading(true);
    try {
      const r = await fetch(
        `${BACKEND}/api/ads/${jobId}/render?format=${encodeURIComponent(fmt)}&variant_index=${variant.variant_index}`
      );
      const data = await r.json();
      if (data.video_url) {
        setVideoUrl(data.video_url);
        setRenderError("");
      } else if (data.error) {
        setVideoUrl("");
        setRenderError(data.error);
      }
    } catch {
      setVideoUrl("");
      setRenderError("Format re-render request failed before the backend returned a video.");
    } finally {
      setFormatLoading(false);
    }
  };

  const handleRerender = async () => {
    setRerendering(true);
    try {
      const r = await fetch(`${BACKEND}/api/ads/${jobId}/edit`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          variant_index: variant.variant_index,
          output_format: activeFormat,
          // pass updated scenes implicitly — server will use the patched state
        }),
      });
      const data = await r.json();
      if (data.video_url) {
        setVideoUrl(data.video_url);
        setRenderError("");
        setShowEditor(false);
      } else if (data.error) {
        setVideoUrl("");
        setRenderError(data.error);
      }
    } catch {
      setVideoUrl("");
      setRenderError("Scene re-render request failed before the backend returned a video.");
    } finally {
      setRerendering(false);
    }
  };

  const updateScene = (idx: number, field: keyof SceneData, value: string) => {
    setScenes((prev) =>
      prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s))
    );
  };

  return (
    <div className={`variant-card${isTop ? " is-top" : ""}`}>
      {isTop && <div className="top-pick-banner">★ Top Pick — Highest Creative Score</div>}

      {/* Header */}
      <div className="card-header">
        <div>
          <div className="card-label">{variant.variant_label}</div>
          <div className="card-hook">"{variant.hook}"</div>
        </div>
        <div className="score-badge">
          <div className={`score-number ${scoreColor(variant.creative_score)}`}>
            {variant.creative_score}
          </div>
          <div className="score-label">Score</div>
        </div>
      </div>

      {/* Format switcher */}
      <div className="format-switcher">
        {["16:9", "9:16", "1:1"].map((fmt) => (
          <button
            key={fmt}
            className={`format-btn${activeFormat === fmt ? " active" : ""}`}
            onClick={() => handleFormatSwitch(fmt)}
            disabled={formatLoading}
          >
            {formatLabel(fmt)}
          </button>
        ))}
        {formatLoading && (
          <span className="format-loading">
            <span className="spinner" /> Rendering…
          </span>
        )}
      </div>

      {/* Video */}
      <div className={`video-container ${showAdvancedEditor ? "editor-mode" : ratioClass(activeFormat)}`}>
        {showAdvancedEditor && videoUrl ? (
          <VideoEditor videoUrl={videoUrl} />
        ) : videoUrl && videoUrl.startsWith("http") ? (
          <video
            ref={videoRef}
            key={videoUrl}
            controls
            autoPlay
            muted
            playsInline
          >
            <source src={videoUrl} type="video/mp4" />
          </video>
        ) : videoUrl === "" ? (
          <div className="video-placeholder" style={{ flexDirection: "column", gap: 8 }}>
            <span style={{ fontSize: "2rem" }}>⚠️</span>
            <span style={{ fontWeight: 600 }}>Video render failed</span>
            <span style={{ fontSize: "0.8rem", opacity: 0.7 }}>
              {renderError || "No render details were returned by the backend."}
            </span>
          </div>
        ) : (
          <div className="video-placeholder">
            <span className="spinner" />
            <span>Rendering video…</span>
          </div>
        )}
      </div>


      {/* Footer */}
      <div className="card-footer">
        <div className="score-rationale">"{variant.score_rationale}"</div>
        <div className="cta-text">
          CTA: <span>{variant.call_to_action}</span>
        </div>
        <div className="card-actions">
          <button className="btn-edit" style={{ background: '#5e6ad2', color: 'white', border: 'none' }} onClick={() => setShowAdvancedEditor((v) => !v)}>
            {showAdvancedEditor ? "Close Advanced Editor" : "Open Advanced Editor"}
          </button>
          <button className="btn-edit" onClick={() => setShowEditor((v) => !v)}>
            {showEditor ? "Close Scene Editor" : "Edit Scenes"}
          </button>
          {videoUrl && videoUrl.startsWith("http") && (
            <a
              className="btn-download"
              href={videoUrl}
              download={`ad-${variant.variant_label.replace(/\s+/g, "-").toLowerCase()}.mp4`}
              target="_blank"
              rel="noreferrer"
            >
              ↓ Download
            </a>
          )}
        </div>
      </div>

      {/* Scene editor */}
      {showEditor && (
        <div className="edit-panel">
          <div className="edit-panel-title">Scene Editor</div>
          <div className="scene-list">
            {scenes.map((scene, idx) => (
              <div key={scene.scene_number} className="scene-row">
                <div className="scene-row-header">
                  <span className="scene-number">Scene {scene.scene_number}</span>
                </div>
                <input
                  className="scene-edit-input"
                  placeholder="Headline text"
                  value={scene.text_overlay}
                  onChange={(e) => updateScene(idx, "text_overlay", e.target.value)}
                />
                <input
                  className="scene-edit-input"
                  placeholder="Image URL (leave blank to keep current)"
                  onChange={(e) => updateScene(idx, "image_url", e.target.value)}
                />
              </div>
            ))}
          </div>
          <button
            className="btn-rerender"
            onClick={handleRerender}
            disabled={rerendering}
          >
            {rerendering ? (
              <>
                <span className="spinner" style={{ marginRight: 6 }} />
                Re-rendering…
              </>
            ) : (
              "Apply & Re-render"
            )}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sample showcase (static, shown before generation)
// ---------------------------------------------------------------------------
function SampleShowcase() {
  return (
    <div className="samples-section">
      <div className="samples-label">Example outputs — every format, every time</div>
      <div className="samples-row">
        {/* Landscape 16:9 */}
        <div className="sample-card landscape">
          <div className="sample-inner">
            <div className="sample-overlay">
              <div className="sample-label">Pain Point Hook</div>
              <div className="sample-text">Tired of slow results?</div>
              <div className="sample-cta">Start Free</div>
            </div>
          </div>
          <span className="sample-format-tag">16:9</span>
        </div>
        {/* Vertical 9:16 */}
        <div className="sample-card vertical">
          <div className="sample-inner">
            <div className="sample-overlay">
              <div className="sample-label">Social Proof</div>
              <div className="sample-text" style={{ fontSize: "0.65rem" }}>
                10k+ brands trust us
              </div>
              <div className="sample-cta">Try Now</div>
            </div>
          </div>
          <span className="sample-format-tag">9:16</span>
        </div>
        {/* Square 1:1 */}
        <div className="sample-card square">
          <div className="sample-inner">
            <div className="sample-overlay">
              <div className="sample-label">Dream Outcome</div>
              <div className="sample-text" style={{ fontSize: "0.75rem" }}>
                Scale from $0 to $100k
              </div>
              <div className="sample-cta">Get Started</div>
            </div>
          </div>
          <span className="sample-format-tag">1:1</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function Home() {
  const [url, setUrl] = useState("");
  const [jobId, setJobId] = useState("");
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [variants, setVariants] = useState<Variant[]>([]);

  const handleGenerate = async () => {
    if (!url.trim() || isGenerating) return;

    setIsGenerating(true);
    setProgress(2);
    setStatus("Connecting to backend…");
    setError("");
    setVariants([]);
    setJobId("");

    try {
      const res = await fetch(`${BACKEND}/api/ads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), tenant_id: "demo" }),
      });
      const data = await res.json();
      const id: string = data.job_id;
      setJobId(id);

      const es = new EventSource(`${BACKEND}/api/ads/stream/${id}`);

      es.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          const pct: number = msg.progress ?? 0;
          const stat: string = msg.status ?? "";
          const vars: Variant[] = msg.variants ?? [];

          setProgress(pct);
          if (stat === "SUCCESS" && vars.some((v) => !v.video_url)) {
            setStatus("FAILED: Backend returned SUCCESS with an empty video_url. This usually means the live backend is running stale code or missing the latest render error propagation fix.");
          } else {
            setStatus(stat);
          }

          if (vars.length > 0) setVariants(vars);

          if (stat.startsWith("FAILED")) {
            setError(stat.replace("FAILED:", "").trim());
            es.close();
            setIsGenerating(false);
          } else if (stat === "SUCCESS" && vars.some((v) => !v.video_url)) {
            setError("Backend returned SUCCESS with an empty video_url. Check that the live backend has the latest deployment and inspect /api/debug/runtime on that backend.");
            es.close();
            setIsGenerating(false);
          } else if (stat === "SUCCESS") {
            es.close();
            setIsGenerating(false);
          }
        } catch {
          // non-JSON event — ignore
        }
      };

      es.onerror = () => {
        setError("Lost connection to progress stream.");
        es.close();
        setIsGenerating(false);
      };
    } catch {
      setError(`Cannot reach backend at ${BACKEND}. Is Uvicorn running?`);
      setIsGenerating(false);
    }
  };

  const topVariantIdx = variants.length
    ? variants.reduce((best, v, i) =>
        v.creative_score > variants[best].creative_score ? i : best, 0)
    : -1;

  const showGallery = variants.length > 0;
  const showProgress = isGenerating || (progress > 0 && !showGallery);

  return (
    <div className="page-wrapper">
      {/* Nav */}
      <nav className="navbar">
        <div className="container">
          <div className="navbar-inner">
            <a href="/" className="logo">
              <div className="logo-mark">A</div>
              <span className="logo-text">AdStudio</span>
            </a>
            <div className="navbar-actions">
              <ThemeToggle />
              <span className="nav-badge">Beta</span>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero */}
      {!showGallery && (
        <section className="hero">
          <div className="container">
            <div className="hero-eyebrow">⚡ URL → Scored Ad in &lt; 1 min</div>

            <h1 className="hero-title">
              Turn any URL into{" "}
              <span className="gradient-text">a winning video ad</span>
              <br />
              with AI Creative Scoring
            </h1>

            <p className="hero-sub">
              Paste a landing page. Get a scored, captioned, multi-format video ad — tailored with a
              winning creative angle. No brief. No agency.
            </p>

            <p className="hero-proof">
              16:9 · 9:16 · 1:1 — burned-in captions — brand kit extraction — scene editor
            </p>

            {/* URL input */}
            <div className="url-form">
              <div className="url-input-row">
                <input
                  type="url"
                  className="url-input"
                  placeholder="https://your-product-page.com"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleGenerate()}
                  disabled={isGenerating}
                />
                <button
                  className="btn-generate"
                  onClick={handleGenerate}
                  disabled={isGenerating || !url.trim()}
                >
                  {isGenerating ? "Generating…" : "Generate Ads →"}
                </button>
              </div>
              <div className="url-hint">
                Works on product pages, landing pages, Shopify stores, SaaS sites
              </div>
            </div>

            {/* Error Banner */}
            {error && (
              <div className="error-banner">
                <span className="error-icon">⚠️</span>
                <div className="error-message-content">
                  <span className="error-title">Generation Failed</span>
                  <span className="error-text">{error}</span>
                </div>
              </div>
            )}

            {/* Progress */}
            {showProgress && (
              <div className="progress-section">
                <div className="progress-header">
                  <span className="progress-label">Generating your ads</span>
                  <span className="progress-pct">{progress}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <div className="progress-status">{status}</div>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Gallery */}
      {showGallery && (
        <section className="gallery-section">
          <div className="container">
            <div className="gallery-header">
              <h2 className="gallery-title">Your Ad Variant</h2>
              <p className="gallery-sub">
                Scored by AI · Edit scenes · Switch format · Download MP4
              </p>
            </div>

            <div className="gallery-grid">
              {variants.map((v, i) => (
                <VariantCard
                  key={v.variant_index}
                  variant={v}
                  jobId={jobId}
                  isTop={variants.length > 1 && i === topVariantIdx}
                />
              ))}
            </div>

            <div className="remix-bar">
              <p>Not happy with these? Try a different angle.</p>
              <button
                className="btn-remix"
                onClick={() => {
                  setVariants([]);
                  setProgress(0);
                  setStatus("");
                  setJobId("");
                }}
              >
                ← New URL / Remix
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Feature strip — only on landing */}
      {!showGallery && !isGenerating && (
        <>
          <section className="features">
            <div className="container">
              <div className="features-grid">
                <div className="feature-card">
                  <div className="feature-icon purple">🎯</div>
                  <div className="feature-title">AI Creative Scoring</div>
                  <div className="feature-desc">
                    Every variant is scored 0–100 on hook strength, CTA clarity, and message-market
                    fit — so you test winners, not guesses.
                  </div>
                </div>

                <div className="feature-card">
                  <div className="feature-icon green">🔀</div>
                  <div className="feature-title">Tailored Creative Angle</div>
                  <div className="feature-desc">
                    Pain Point, Social Proof, or Dream Outcome — a tailored creative concept
                    optimized for your brand from a single URL.
                  </div>
                </div>

                <div className="feature-card">
                  <div className="feature-icon yellow">📐</div>
                  <div className="feature-title">Every Format, On-Demand</div>
                  <div className="feature-desc">
                    16:9 (YouTube), 9:16 (TikTok/Reels), 1:1 (Feed). Switch in one click — the
                    same ad, perfectly reframed.
                  </div>
                </div>

                <div className="feature-card">
                  <div className="feature-icon pink">💬</div>
                  <div className="feature-title">Burned-in Captions</div>
                  <div className="feature-desc">
                    Word-level timestamps drive synced animated captions. 85% of social video
                    is watched muted — your ads are ready.
                  </div>
                </div>
              </div>
            </div>
          </section>

          <SampleShowcase />
        </>
      )}

      {/* Footer */}
      <footer className="footer">
        <div className="container">
          AdStudio — AI Ad Creation Platform · Beta
        </div>
      </footer>
    </div>
  );
}
