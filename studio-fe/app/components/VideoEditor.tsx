'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  Edit, Canvas, Controls, Timeline, UIController, VideoExporter,
} from '@shotstack/shotstack-studio';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
type ModalType = 'text' | 'subtitle' | 'image' | 'audio' | null;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyClip = Record<string, any>;

interface SelectedClip {
  trackIndex: number;
  clipIndex: number;
  raw: AnyClip;
}

// ─────────────────────────────────────────────────────────────────────────────
// Small helpers
// ─────────────────────────────────────────────────────────────────────────────
function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="ve-field-row">
      <label className="ve-field-label">{label}</label>
      <div className="ve-field-ctrl">{children}</div>
    </div>
  );
}

// Position aligning helper
const posAlign: Record<string, { horizontal: "center" | "left" | "right"; vertical: "top" | "middle" | "bottom" }> = {
  top:    { horizontal: 'center', vertical: 'top'    },
  center: { horizontal: 'center', vertical: 'middle' },
  bottom: { horizontal: 'center', vertical: 'bottom' },
};

const getPosFromAlign = (align?: { horizontal?: string; vertical?: string }): string => {
  if (!align) return 'center';
  if (align.vertical === 'top') return 'top';
  if (align.vertical === 'bottom') return 'bottom';
  return 'center';
};

// ─────────────────────────────────────────────────────────────────────────────
// Modal: Add Text / Title
// ─────────────────────────────────────────────────────────────────────────────
interface ModalProps {
  defaultStart: number;
  onAdd: (d: AnyClip) => void;
  onClose: () => void;
}

function TextModal({ defaultStart, onAdd, onClose }: ModalProps) {
  const [text, setText]       = useState('Your Title Here');
  const [size, setSize]       = useState(72);
  const [color, setColor]     = useState('#ffffff');
  const [shadow, setShadow]   = useState(true);
  const [pos, setPos]         = useState('center');
  const [start, setStart]     = useState(parseFloat(defaultStart.toFixed(2)));
  const [length, setLength]   = useState(5);

  return (
    <div className="ve-modal-inner">
      <div className="ve-modal-head">
        <span className="ve-modal-icon">T</span>
        <div>
          <div className="ve-modal-title">Add Text / Title</div>
          <div className="ve-modal-sub">Overlay bold text on any frame</div>
        </div>
      </div>
      <FieldRow label="Text">
        <textarea className="ve-input ve-textarea" value={text}
          onChange={e => setText(e.target.value)} rows={3} placeholder="Enter text…" />
      </FieldRow>
      <div className="ve-field-pair">
        <FieldRow label="Font size (px)">
          <input className="ve-input" type="number" value={size} min={12} max={300}
            onChange={e => setSize(Number(e.target.value))} />
        </FieldRow>
        <FieldRow label="Color">
          <input type="color" value={color} onChange={e => setColor(e.target.value)}
            className="ve-color-input" />
        </FieldRow>
      </div>
      <div className="ve-field-pair">
        <FieldRow label="Position">
          <select className="ve-input" value={pos} onChange={e => setPos(e.target.value)}>
            <option value="top">Top</option>
            <option value="center">Center</option>
            <option value="bottom">Bottom</option>
          </select>
        </FieldRow>
        <FieldRow label="Text shadow">
          <label className="ve-toggle">
            <input type="checkbox" checked={shadow} onChange={e => setShadow(e.target.checked)} />
            <span className="ve-toggle-track" />
          </label>
        </FieldRow>
      </div>
      <div className="ve-field-pair">
        <FieldRow label="Start time (s)">
          <input className="ve-input" type="number" value={start} min={0} step={0.1}
            onChange={e => setStart(Number(e.target.value))} />
        </FieldRow>
        <FieldRow label="Duration (s)">
          <input className="ve-input" type="number" value={length} min={0.5} step={0.5}
            onChange={e => setLength(Number(e.target.value))} />
        </FieldRow>
      </div>
      <div className="ve-modal-footer">
        <button className="ve-btn-ghost" onClick={onClose}>Cancel</button>
        <button className="ve-btn-primary" onClick={() => onAdd({ text, size, color, shadow, pos, start, length })}>
          Add to Timeline
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Modal: Add Subtitle
// ─────────────────────────────────────────────────────────────────────────────
function SubtitleModal({ defaultStart, onAdd, onClose }: ModalProps) {
  const [text, setText]     = useState('');
  const [start, setStart]   = useState(parseFloat(defaultStart.toFixed(2)));
  const [length, setLength] = useState(3);

  return (
    <div className="ve-modal-inner">
      <div className="ve-modal-head">
        <span className="ve-modal-icon">💬</span>
        <div>
          <div className="ve-modal-title">Add Subtitle</div>
          <div className="ve-modal-sub">Timed caption strip at the bottom of the frame</div>
        </div>
      </div>
      <FieldRow label="Caption text">
        <textarea className="ve-input ve-textarea" value={text}
          onChange={e => setText(e.target.value)} rows={2}
          placeholder="Enter subtitle line…" />
      </FieldRow>
      <div className="ve-field-pair">
        <FieldRow label="Start time (s)">
          <input className="ve-input" type="number" value={start} min={0} step={0.1}
            onChange={e => setStart(Number(e.target.value))} />
        </FieldRow>
        <FieldRow label="Duration (s)">
          <input className="ve-input" type="number" value={length} min={0.5} step={0.5}
            onChange={e => setLength(Number(e.target.value))} />
        </FieldRow>
      </div>
      <div className="ve-modal-footer">
        <button className="ve-btn-ghost" onClick={onClose}>Cancel</button>
        <button className="ve-btn-primary" disabled={!text.trim()}
          onClick={() => onAdd({ text, start, length })}>
          Add Subtitle
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Modal: Add Image Overlay
// ─────────────────────────────────────────────────────────────────────────────
function ImageModal({ defaultStart, onAdd, onClose }: ModalProps) {
  const [src, setSrc]       = useState('');
  const [start, setStart]   = useState(parseFloat(defaultStart.toFixed(2)));
  const [length, setLength] = useState(5);
  const [opacity, setOpacity] = useState(1);
  const [fit, setFit]       = useState('contain');

  return (
    <div className="ve-modal-inner">
      <div className="ve-modal-head">
        <span className="ve-modal-icon">🖼</span>
        <div>
          <div className="ve-modal-title">Add Image Overlay</div>
          <div className="ve-modal-sub">Layer a logo, watermark, or graphic on the video</div>
        </div>
      </div>
      <FieldRow label="Image URL">
        <input className="ve-input" type="url" value={src}
          onChange={e => setSrc(e.target.value)}
          placeholder="https://example.com/image.png" />
      </FieldRow>
      <div className="ve-field-pair">
        <FieldRow label="Start time (s)">
          <input className="ve-input" type="number" value={start} min={0} step={0.1}
            onChange={e => setStart(Number(e.target.value))} />
        </FieldRow>
        <FieldRow label="Duration (s)">
          <input className="ve-input" type="number" value={length} min={0.5} step={0.5}
            onChange={e => setLength(Number(e.target.value))} />
        </FieldRow>
      </div>
      <div className="ve-field-pair">
        <FieldRow label={`Opacity (${Math.round(opacity * 100)}%)`}>
          <input type="range" min={0} max={1} step={0.02} value={opacity}
            onChange={e => setOpacity(Number(e.target.value))} className="ve-slider" />
        </FieldRow>
        <FieldRow label="Fit mode">
          <select className="ve-input" value={fit} onChange={e => setFit(e.target.value)}>
            <option value="contain">Contain</option>
            <option value="cover">Cover</option>
            <option value="crop">Crop</option>
            <option value="none">None (original size)</option>
          </select>
        </FieldRow>
      </div>
      <div className="ve-modal-footer">
        <button className="ve-btn-ghost" onClick={onClose}>Cancel</button>
        <button className="ve-btn-primary" disabled={!src.trim()}
          onClick={() => onAdd({ src, start, length, opacity, fit })}>
          Add Image
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Modal: Add Audio Track
// ─────────────────────────────────────────────────────────────────────────────
function AudioModal({ defaultStart, onAdd, onClose }: ModalProps) {
  const [src, setSrc]       = useState('');
  const [start, setStart]   = useState(parseFloat(defaultStart.toFixed(2)));
  const [volume, setVolume] = useState(0.8);
  const [effect, setEffect] = useState('fadeInFadeOut');

  return (
    <div className="ve-modal-inner">
      <div className="ve-modal-head">
        <span className="ve-modal-icon">♪</span>
        <div>
          <div className="ve-modal-title">Add Audio Track</div>
          <div className="ve-modal-sub">Background music, voiceover, or sound effects</div>
        </div>
      </div>
      <FieldRow label="Audio URL">
        <input className="ve-input" type="url" value={src}
          onChange={e => setSrc(e.target.value)}
          placeholder="https://example.com/audio.mp3" />
      </FieldRow>
      <FieldRow label="Start time (s)">
        <input className="ve-input" type="number" value={start} min={0} step={0.1}
          onChange={e => setStart(Number(e.target.value))} />
      </FieldRow>
      <FieldRow label={`Volume (${Math.round(volume * 100)}%)`}>
        <input type="range" min={0} max={1} step={0.02} value={volume}
          onChange={e => setVolume(Number(e.target.value))} className="ve-slider" />
      </FieldRow>
      <FieldRow label="Fade effect">
        <select className="ve-input" value={effect} onChange={e => setEffect(e.target.value)}>
          <option value="none">None</option>
          <option value="fadeIn">Fade In</option>
          <option value="fadeOut">Fade Out</option>
          <option value="fadeInFadeOut">Fade In + Out</option>
        </select>
      </FieldRow>
      <div className="ve-modal-footer">
        <button className="ve-btn-ghost" onClick={onClose}>Cancel</button>
        <button className="ve-btn-primary" disabled={!src.trim()}
          onClick={() => onAdd({ src, start, volume, effect })}>
          Add Audio
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main VideoEditor component
// ─────────────────────────────────────────────────────────────────────────────
export default function VideoEditor({ videoUrl }: { videoUrl: string }) {
  const timelineRef     = useRef<HTMLDivElement>(null);
  const editRef         = useRef<Edit | null>(null);
  const canvasRef       = useRef<Canvas | null>(null);
  const timelineInstRef = useRef<Timeline | null>(null);
  const controlsRef     = useRef<Controls | null>(null);
  const uiRef           = useRef<ReturnType<typeof UIController.create> | null>(null);

  const [status, setStatus]             = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMsg, setErrorMsg]         = useState('');
  const [modal, setModal]               = useState<ModalType>(null);
  const [selectedClip, setSelectedClip] = useState<SelectedClip | null>(null);
  const [exporting, setExporting]       = useState(false);
  const [zoomPct, setZoomPct]           = useState(100);
  const [playbackTime, setPlaybackTime] = useState(0);
  const [totalDuration, setTotalDuration] = useState(0);

  // ── Cleanup ────────────────────────────────────────────────────────────────
  const destroyAll = useCallback(() => {
    try { timelineInstRef.current?.dispose?.(); } catch { /* ignore */ }
    try { (controlsRef.current as any)?.dispose?.(); } catch { /* ignore */ }
    try { uiRef.current?.dispose?.();           } catch { /* ignore */ }
    try { canvasRef.current?.dispose?.();       } catch { /* ignore */ }
    timelineInstRef.current = null;
    controlsRef.current     = null;
    uiRef.current           = null;
    canvasRef.current       = null;
    editRef.current         = null;
  }, []);

  // ── Load SDK ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!timelineRef.current || !videoUrl) return;

    let active = true;

    destroyAll();
    setStatus('loading');
    setSelectedClip(null);
    setPlaybackTime(0);
    setTotalDuration(0);

    // Strip query params before extracting filename (e.g. ?t=... suffixes)
    const cleanUrl  = videoUrl.split('?')[0];
    const filename  = cleanUrl.split('/').pop() ?? '';

    // Dynamically pass the backend origin to the proxy so it doesn't rely on env vars
    let backendOrigin = '';
    try {
      backendOrigin = new URL(videoUrl).origin;
    } catch (e) {
      // fallback
    }

    // Use our custom Next.js API route which properly forwards Range headers.
    // If the backend is running locally (localhost/127.0.0.1), we load it directly in the browser
    // since the Vercel cloud server cannot access the user's localhost.
    const isLocal = cleanUrl.includes('localhost') || cleanUrl.includes('127.0.0.1');
    const proxiedUrl = isLocal
      ? cleanUrl
      : `${window.location.origin}/api/video_stream/${filename}${backendOrigin ? `?backend=${encodeURIComponent(backendOrigin)}` : ''}`;

    const load = async () => {
      try {
        const template = {
          timeline: {
            tracks: [
              { clips: [{ asset: { type: 'video', src: proxiedUrl, volume: 1 }, start: 0, length: 60 }] },
            ],
          },
          output: { format: 'mp4', resolution: 'hd' },
        };

        const edit   = new Edit(template as any);
        const canvas = new Canvas(edit);

        if (!active) {
          canvas.dispose();
          return;
        }

        editRef.current   = edit;
        canvasRef.current = canvas;

        // UIController MUST be created before canvas.load()
        const ui = UIController.create(edit, canvas);
        uiRef.current = ui;

        // Register custom toolbar buttons (positioned at the playhead on click)
        ui.registerButton({
          id: 've-add-text',
          icon: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 3H13"/><path d="M8 3V13"/><path d="M5 13H11"/></svg>`,
          tooltip: 'Add Text',
        });
        ui.registerButton({
          id: 've-add-subtitle',
          icon: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><rect x="2" y="10" width="12" height="4" rx="1"/><path d="M4 12h4"/></svg>`,
          tooltip: 'Add Subtitle',
        });
        ui.registerButton({
          id: 've-add-image',
          icon: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><rect x="2" y="2" width="12" height="12" rx="2"/><circle cx="6" cy="6" r="1.5"/><path d="M14 10l-3-3-4 4-2-2-3 3"/></svg>`,
          tooltip: 'Add Image',
        });
        ui.registerButton({
          id: 've-add-audio',
          icon: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M9 2L5 6H2v4h3l4 4V2z"/><path d="M12 5.5a4 4 0 010 5"/></svg>`,
          tooltip: 'Add Audio',
          dividerBefore: true,
        });

        ui.on('button:ve-add-text',     () => setModal('text'));
        ui.on('button:ve-add-subtitle', () => setModal('subtitle'));
        ui.on('button:ve-add-image',    () => setModal('image'));
        ui.on('button:ve-add-audio',    () => setModal('audio'));

        // Wait one animation frame so React has painted ve-canvas-wrap
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        if (!active) {
          ui.dispose();
          canvas.dispose();
          return;
        }

        await canvas.load();
        if (!active) {
          ui.dispose();
          canvas.dispose();
          return;
        }

        await edit.load();
        if (!active) {
          ui.dispose();
          canvas.dispose();
          return;
        }

        canvas.resize();
        canvas.zoomToFit();
        setZoomPct(Math.round(canvas.getZoom() * 100));
        setTotalDuration(edit.totalDuration ?? 0);

        const timeline = new Timeline(edit, timelineRef.current!, { resizable: true });
        timelineInstRef.current = timeline;
        await timeline.load();
        if (!active) {
          timeline.dispose();
          ui.dispose();
          canvas.dispose();
          return;
        }

        const controls = new Controls(edit);
        controlsRef.current = controls;
        await controls.load();
        if (!active) {
          (controls as any).dispose?.();
          timeline.dispose();
          ui.dispose();
          canvas.dispose();
          return;
        }

        // ── Events ──────────────────────────────────────────────────────
        edit.events.on('clip:selected', (data: AnyClip) => {
          if (!active) return;
          const raw = edit.getClip(data.trackIndex, data.clipIndex) as AnyClip;
          if (raw) setSelectedClip({ trackIndex: data.trackIndex, clipIndex: data.clipIndex, raw });
        });
        edit.events.on('selection:cleared', () => {
          if (!active) return;
          setSelectedClip(null);
        });
        edit.events.on('clip:updated', (data: AnyClip) => {
          if (!active) return;
          const raw = edit.getClip(data.trackIndex, data.clipIndex) as AnyClip;
          if (raw) setSelectedClip(prev => prev ? { ...prev, raw } : prev);
        });
        edit.events.on('duration:changed', () => {
          if (!active) return;
          setTotalDuration(edit.totalDuration ?? 0);
        });
        edit.events.on('playback:play',  () => {
          if (!active) return;
          const tick = setInterval(() => {
            setPlaybackTime(editRef.current?.playbackTime ?? 0);
          }, 200);
          const unsub = edit.events.on('playback:pause', () => {
            clearInterval(tick);
            unsub();
          });
        });

        setStatus('ready');
        requestAnimationFrame(() => {
          if (active) {
            canvas.resize();
            canvas.zoomToFit();
          }
        });

      } catch (err: unknown) {
        if (!active) return;
        const msg = err instanceof Error ? err.message : String(err);
        console.error('[VideoEditor]', err);
        setErrorMsg(msg);
        setStatus('error');
      }
    };

    load();
    return () => {
      active = false;
      destroyAll();
    };
  }, [videoUrl, destroyAll]);

  // ── Toolbar actions ────────────────────────────────────────────────────────
  const undo    = () => editRef.current?.undo();
  const redo    = () => editRef.current?.redo();
  const zoomIn  = () => {
    if (!canvasRef.current) return;
    const z = Math.min(4, canvasRef.current.getZoom() + 0.15);
    canvasRef.current.setZoom(z);
    setZoomPct(Math.round(z * 100));
  };
  const zoomOut = () => {
    if (!canvasRef.current) return;
    const z = Math.max(0.1, canvasRef.current.getZoom() - 0.15);
    canvasRef.current.setZoom(z);
    setZoomPct(Math.round(z * 100));
  };
  const zoomFit = () => {
    if (!canvasRef.current) return;
    canvasRef.current.zoomToFit();
    setZoomPct(Math.round(canvasRef.current.getZoom() * 100));
  };

  const handleExport = async () => {
    if (!editRef.current || !canvasRef.current) return;
    setExporting(true);
    try {
      const exporter = new VideoExporter(editRef.current, canvasRef.current);
      await exporter.export('adstudio-export.mp4', 25);
    } catch (e) {
      console.error('Export failed:', e);
    } finally {
      setExporting(false);
    }
  };

  // ── Add asset handlers ─────────────────────────────────────────────────────
  const handleAddText = async (d: AnyClip) => {
    if (!editRef.current) return;
    await editRef.current.addTrack(0, {
      clips: [{
        asset: {
          type: 'rich-text',
          text: d.text,
          font: {
            family: 'Work Sans', size: d.size, weight: 700,
            color: d.color, opacity: 1,
            ...(d.shadow ? { lineHeight: 1.2 } : {}),
          },
          align: posAlign[d.pos] || posAlign.center,
          background: {
            color: 'rgba(0,0,0,0.55)',
            borderRadius: 8,
          },
        },
        start: d.start,
        length: d.length,
        width: 1680,
        height: d.pos === 'center' ? 320 : 200,
      }],
    });
    setModal(null);
  };

  const handleAddSubtitle = async (d: AnyClip) => {
    if (!editRef.current) return;
    await editRef.current.addTrack(0, {
      clips: [{
        asset: {
          type: 'rich-text',
          text: d.text,
          font: { family: 'Work Sans', size: 46, weight: 600, color: '#ffffff', opacity: 1 },
          align: { horizontal: 'center', vertical: 'bottom' },
          background: {
            color: 'rgba(0,0,0,0.78)',
            borderRadius: 4,
          },
        },
        start: d.start,
        length: d.length,
        width: 1600,
        height: 130,
        offset: { x: 0, y: 0.38 },
      }],
    });
    setModal(null);
  };

  const handleAddImage = async (d: AnyClip) => {
    if (!editRef.current) return;
    await editRef.current.addTrack(0, {
      clips: [{
        asset: { type: 'image', src: d.src },
        start: d.start, length: d.length,
        opacity: d.opacity,
        fit: d.fit,
      }],
    });
    setModal(null);
  };

  const handleAddAudio = async (d: AnyClip) => {
    if (!editRef.current) return;
    await editRef.current.addTrack(0, {
      clips: [{
        asset: {
          type: 'audio', src: d.src, volume: d.volume,
          ...(d.effect !== 'none' ? { effect: d.effect } : {}),
        },
        start: d.start,
        length: 120,
      }],
    });
    setModal(null);
  };

  // ── Modify asset properties handlers ───────────────────────────────────────
  const handleStartChange = async (newStart: number) => {
    if (!editRef.current || !selectedClip) return;
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { start: newStart });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, start: newStart } } : prev);
  };

  const handleLengthChange = async (newLength: number) => {
    if (!editRef.current || !selectedClip) return;
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { length: newLength });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, length: newLength } } : prev);
  };

  const handleTextChange = async (newText: string) => {
    if (!editRef.current || !selectedClip) return;
    const asset = { ...selectedClip.raw.asset, text: newText };
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { asset });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, asset } } : prev);
  };

  const handleFontSizeChange = async (newSize: number) => {
    if (!editRef.current || !selectedClip) return;
    const font = { ...selectedClip.raw.asset.font, size: newSize };
    const asset = { ...selectedClip.raw.asset, font };
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { asset });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, asset } } : prev);
  };

  const handleColorChange = async (newColor: string) => {
    if (!editRef.current || !selectedClip) return;
    const font = { ...selectedClip.raw.asset.font, color: newColor };
    const asset = { ...selectedClip.raw.asset, font };
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { asset });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, asset } } : prev);
  };

  const handleAlignChange = async (newPos: string) => {
    if (!editRef.current || !selectedClip) return;
    const align = posAlign[newPos];
    const asset = { ...selectedClip.raw.asset, align };
    const updates: Record<string, any> = {
      asset,
      height: newPos === 'center' ? 320 : 200,
    };
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, updates);
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, ...updates } } : prev);
  };

  const handleSrcChange = async (newSrc: string) => {
    if (!editRef.current || !selectedClip) return;
    const asset = { ...selectedClip.raw.asset, src: newSrc };
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { asset });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, asset } } : prev);
  };

  const handleFitChange = async (newFit: any) => {
    if (!editRef.current || !selectedClip) return;
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { fit: newFit });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, fit: newFit } } : prev);
  };

  const handleVolumeChange = async (v: number) => {
    if (!editRef.current || !selectedClip) return;
    const asset = { ...selectedClip.raw.asset, volume: v };
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { asset });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, asset } } : prev);
  };

  const handleOpacityChange = async (opacity: number) => {
    if (!editRef.current || !selectedClip) return;
    await editRef.current.updateClip(selectedClip.trackIndex, selectedClip.clipIndex, { opacity });
    setSelectedClip(prev => prev ? { ...prev, raw: { ...prev.raw, opacity } } : prev);
  };

  const handleDeleteClip = async () => {
    if (!editRef.current || !selectedClip) return;
    await editRef.current.deleteClip(selectedClip.trackIndex, selectedClip.clipIndex);
    setSelectedClip(null);
  };

  // ── Render ────────────────────────────────────────────────────────────────
  const isReady   = status === 'ready';
  const clip      = selectedClip?.raw;
  const assetType = clip?.asset?.type as string | undefined;

  const fmtTime = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  return (
    <div className="ve-root">

      {/* ── Full-editor overlay (loading / error) ─────────────────────── */}
      {status !== 'ready' && (
        <div className="ve-full-overlay">
          {status === 'loading' ? (
            <>
              <div className="ve-ol-spinner"><span className="spinner" /></div>
              <div className="ve-ol-title">Loading editor…</div>
              <div className="ve-ol-sub">Initialising PIXI canvas · Building timeline</div>
            </>
          ) : (
            <>
              <div style={{ fontSize: '2.5rem' }}>⚠️</div>
              <div className="ve-ol-title" style={{ color: 'var(--red)' }}>Editor failed to load</div>
              <div className="ve-ol-sub">{errorMsg}</div>
            </>
          )}
        </div>
      )}

      {/* ── Toolbar ───────────────────────────────────────────────────── */}
      <div className="ve-toolbar">
        {/* Left: history + zoom */}
        <div className="ve-tb-group">
          <button className="ve-tb-btn" onClick={undo} disabled={!isReady} title="Undo (Ctrl+Z)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M3 7v6h6"/><path d="M21 17A9 9 0 006 6.3L3 9"/>
            </svg>
            Undo
          </button>
          <button className="ve-tb-btn" onClick={redo} disabled={!isReady} title="Redo (Ctrl+Y)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0115-2.7L21 9"/>
            </svg>
            Redo
          </button>
        </div>
        <div className="ve-tb-sep" />
        <div className="ve-tb-group">
          <button className="ve-tb-icon-btn" onClick={zoomOut} disabled={!isReady} title="Zoom out">−</button>
          <span className="ve-tb-zoom">{zoomPct}%</span>
          <button className="ve-tb-icon-btn" onClick={zoomIn}  disabled={!isReady} title="Zoom in">+</button>
          <button className="ve-tb-btn" onClick={zoomFit} disabled={!isReady} title="Fit to screen">Fit</button>
        </div>
        {/* Center: title + time */}
        <div className="ve-tb-center">
          <span className="ve-tb-brand">⚡ AdStudio Editor</span>
          {isReady && (
            <span className="ve-tb-time">
              {fmtTime(playbackTime)} / {fmtTime(totalDuration)}
            </span>
          )}
        </div>
        {/* Right: export */}
        <div className="ve-tb-group">
          <button
            className="ve-tb-export"
            onClick={handleExport}
            disabled={!isReady || exporting}
          >
            {exporting
              ? <><span className="spinner" style={{ width: 11, height: 11, borderWidth: 2 }} /> Exporting…</>
              : <><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 3v13M5 14l7 7 7-7"/><path d="M3 20h18"/></svg> Export MP4</>
            }
          </button>
        </div>
      </div>

      {/* ── Main area ─────────────────────────────────────────────────── */}
      {/* opacity:0 instead of visibility:hidden — flex heights must resolve so  */}
      {/* PIXI reads real offsetWidth/offsetHeight from ve-canvas-wrap at load.  */}
      <div
        className="ve-main"
        style={status === 'loading' ? { opacity: 0, pointerEvents: 'none' } : undefined}
      >

        {/* Left panel: asset tools */}
        <div className="ve-left-panel">
          <div className="ve-panel-heading">Add to Timeline</div>

          {([
            { key: 'text',     icon: 'T',  name: 'Text / Title',  desc: 'Animated heading overlay'   },
            { key: 'subtitle', icon: '💬', name: 'Subtitle',      desc: 'Timed caption strip'         },
            { key: 'image',    icon: '🖼', name: 'Image Overlay', desc: 'Logo, graphic, watermark'    },
            { key: 'audio',    icon: '♪',  name: 'Audio Track',   desc: 'Music, voiceover, SFX'      },
          ] as const).map(({ key, icon, name, desc }) => (
            <button
              key={key}
              className="ve-asset-btn"
              onClick={() => setModal(key)}
              disabled={!isReady}
            >
              <span className="ve-asset-icon">{icon}</span>
              <span className="ve-asset-text">
                <span className="ve-asset-name">{name}</span>
                <span className="ve-asset-desc">{desc}</span>
              </span>
            </button>
          ))}

          <div className="ve-panel-heading" style={{ marginTop: 16 }}>Keyboard Shortcuts</div>
          <div className="ve-shortcut-list">
            {[
              ['Space', 'Play / Pause'],
              ['Ctrl Z', 'Undo'],
              ['Ctrl Y', 'Redo'],
              ['Del', 'Delete clip'],
              ['← →', 'Seek frame'],
            ].map(([key, label]) => (
              <div className="ve-shortcut-row" key={key}>
                <kbd className="ve-kbd">{key}</kbd>
                <span className="ve-kbd-label">{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Canvas */}
        <div className="ve-canvas-wrap">
          {/* Shotstack mounts PIXI WebGL canvas into this element */}
          <div data-shotstack-studio className="ve-canvas" />
        </div>

        {/* Right panel: properties */}
        <div className="ve-right-panel">
          <div className="ve-panel-heading">Properties</div>
          {!isReady ? (
            <div className="ve-props-empty"><span className="spinner" /></div>
          ) : !selectedClip ? (
            <div className="ve-props-empty">
              <div className="ve-props-empty-icon">🎬</div>
              <div>Click a clip on the timeline to view and edit its properties</div>
            </div>
          ) : (
            <div className="ve-props-body">
              {/* Clip type badge */}
              <div className="ve-clip-type-badge">
                {assetType === 'video'     && '🎥 Video'}
                {assetType === 'audio'     && '🎵 Audio'}
                {assetType === 'image'     && '🖼 Image'}
                {assetType === 'rich-text' && 'T Text/Subtitle'}
                {!assetType               && '— Unknown'}
              </div>

              {/* Timing */}
              <div className="ve-prop-section">
                <div className="ve-prop-section-title">Timing</div>
                <FieldRow label="Start Time (s)">
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={clip?.start ?? 0}
                    onChange={e => handleStartChange(Number(e.target.value))}
                    className="ve-input"
                  />
                </FieldRow>
                <FieldRow label="Duration (s)">
                  <input
                    type="number"
                    min={0.1}
                    step={0.1}
                    value={clip?.length ?? 5}
                    onChange={e => handleLengthChange(Number(e.target.value))}
                    className="ve-input"
                  />
                </FieldRow>
              </div>

              {/* Text content editing */}
              {assetType === 'rich-text' && clip?.asset && (
                <div className="ve-prop-section">
                  <div className="ve-prop-section-title">Text Style</div>
                  <FieldRow label="Text Content">
                    <textarea
                      value={clip.asset.text ?? ''}
                      onChange={e => handleTextChange(e.target.value)}
                      className="ve-input ve-textarea"
                      rows={3}
                    />
                  </FieldRow>
                  <div className="ve-field-pair">
                    <FieldRow label="Font Size">
                      <input
                        type="number"
                        min={12}
                        max={200}
                        value={clip.asset.font?.size ?? 40}
                        onChange={e => handleFontSizeChange(Number(e.target.value))}
                        className="ve-input"
                      />
                    </FieldRow>
                    <FieldRow label="Color">
                      <input
                        type="color"
                        value={clip.asset.font?.color ?? '#ffffff'}
                        onChange={e => handleColorChange(e.target.value)}
                        className="ve-color-input"
                      />
                    </FieldRow>
                  </div>
                  {/* Position Alignment dropdown (if not subtitle) */}
                  {!clip.offset && (
                    <FieldRow label="Alignment">
                      <select
                        value={getPosFromAlign(clip.asset.align)}
                        onChange={e => handleAlignChange(e.target.value)}
                        className="ve-input"
                      >
                        <option value="top">Top</option>
                        <option value="center">Center</option>
                        <option value="bottom">Bottom</option>
                      </select>
                    </FieldRow>
                  )}
                </div>
              )}

              {/* Image source editing */}
              {assetType === 'image' && clip?.asset && (
                <div className="ve-prop-section">
                  <div className="ve-prop-section-title">Image Source</div>
                  <FieldRow label="Source URL">
                    <input
                      type="url"
                      value={clip.asset.src ?? ''}
                      onChange={e => handleSrcChange(e.target.value)}
                      className="ve-input"
                    />
                  </FieldRow>
                  <FieldRow label="Fit Mode">
                    <select
                      value={clip.fit ?? 'contain'}
                      onChange={e => handleFitChange(e.target.value)}
                      className="ve-input"
                    >
                      <option value="contain">Contain</option>
                      <option value="cover">Cover</option>
                      <option value="crop">Crop</option>
                      <option value="none">None</option>
                    </select>
                  </FieldRow>
                </div>
              )}

              {/* Audio source editing */}
              {assetType === 'audio' && clip?.asset && (
                <div className="ve-prop-section">
                  <div className="ve-prop-section-title">Audio Source</div>
                  <FieldRow label="Source URL">
                    <input
                      type="url"
                      value={clip.asset.src ?? ''}
                      onChange={e => handleSrcChange(e.target.value)}
                      className="ve-input"
                    />
                  </FieldRow>
                </div>
              )}

              {/* Volume — video / audio */}
              {(assetType === 'video' || assetType === 'audio') && (
                <div className="ve-prop-section">
                  <div className="ve-prop-section-title">Audio</div>
                  <div className="ve-prop-row">
                    <span className="ve-prop-key">Volume</span>
                    <span className="ve-prop-val">{Math.round((clip?.asset?.volume ?? 1) * 100)}%</span>
                  </div>
                  <input
                    type="range" min={0} max={1} step={0.02}
                    value={clip?.asset?.volume ?? 1}
                    onChange={e => handleVolumeChange(Number(e.target.value))}
                    className="ve-slider"
                  />
                </div>
              )}

              {/* Opacity — image / text */}
              {(assetType === 'image' || assetType === 'rich-text') && (
                <div className="ve-prop-section">
                  <div className="ve-prop-section-title">Visibility</div>
                  <div className="ve-prop-row">
                    <span className="ve-prop-key">Opacity</span>
                    <span className="ve-prop-val">{Math.round((clip?.opacity ?? 1) * 100)}%</span>
                  </div>
                  <input
                    type="range" min={0} max={1} step={0.02}
                    value={clip?.opacity ?? 1}
                    onChange={e => handleOpacityChange(Number(e.target.value))}
                    className="ve-slider"
                  />
                </div>
              )}

              {/* Delete */}
              <button className="ve-delete-btn" onClick={handleDeleteClip}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>
                </svg>
                Delete Clip
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Timeline ─────────────────────────────────────────────────── */}
      <div
        ref={timelineRef}
        data-shotstack-timeline
        className="ve-timeline"
        style={status === 'loading' ? { opacity: 0, pointerEvents: 'none' } : undefined}
      />

      {/* ── Modals ───────────────────────────────────────────────────── */}
      {modal && (
        <div className="ve-backdrop" onClick={() => setModal(null)}>
          <div className="ve-modal" onClick={e => e.stopPropagation()}>
            {modal === 'text'     && <TextModal     defaultStart={playbackTime} onAdd={handleAddText}     onClose={() => setModal(null)} />}
            {modal === 'subtitle' && <SubtitleModal defaultStart={playbackTime} onAdd={handleAddSubtitle} onClose={() => setModal(null)} />}
            {modal === 'image'    && <ImageModal    defaultStart={playbackTime} onAdd={handleAddImage}    onClose={() => setModal(null)} />}
            {modal === 'audio'    && <AudioModal    defaultStart={playbackTime} onAdd={handleAddAudio}    onClose={() => setModal(null)} />}
          </div>
        </div>
      )}
    </div>
  );
}
