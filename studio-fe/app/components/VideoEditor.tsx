import React, { useEffect, useRef, useState } from "react";

interface VideoEditorProps {
  source: Record<string, any>;
  publicToken: string;
  backendUrl: string;
}

export default function VideoEditor({ source, publicToken, backendUrl }: VideoEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let preview: any = null;

    if (!publicToken) {
      setError("Missing NEXT_PUBLIC_CREATOMATE_PUBLIC_TOKEN in frontend.");
      return;
    }

    if (!source || !source.elements) {
      console.warn("VideoEditor: source is empty or missing elements", source);
      setError("Invalid video blueprint source. Check backend payload.");
      return;
    }

    console.log("Initializing Creatomate Editor with source:", source);

    // Deep proxy function to route images/audio through our backend CORS proxy
    const proxyUrl = (url: string) => {
      if (!url || typeof url !== "string" || !url.startsWith("http")) return url;
      if (url.includes("creatomate.com") || url.includes("placehold.co")) return url;
      return `${backendUrl}/api/proxy?url=${encodeURIComponent(url)}`;
    };

    const proxyElements = (elements: any[]): any[] => {
      return elements.map(el => {
        const newEl = { ...el };
        if (newEl.source) {
          newEl.source = proxyUrl(newEl.source);
        }
        if (newEl.elements && Array.isArray(newEl.elements)) {
          newEl.elements = proxyElements(newEl.elements);
        }
        return newEl;
      });
    };

    const proxiedSource = {
      ...source,
      elements: proxyElements(source.elements || [])
    };

    const loadPreview = async () => {
      try {
        if (typeof window !== "undefined") {
          const { Preview } = await import("@creatomate/preview");
          if (!containerRef.current) return;
          
          preview = new Preview(containerRef.current, "player", publicToken);

          preview.onReady = async () => {
            console.log("Creatomate preview is ready. Loading proxied source...");
            await preview.setSource(proxiedSource);
            console.log("Source loaded successfully!");
          };
          
          preview.onLoadError = (err: any) => {
             console.error("Preview load error:", err);
             setError(`Error loading template: ${err.message || err}`);
          };
        }
      } catch (err: any) {
        console.error("Preview SDK error:", err);
        setError("Failed to load video editor: " + (err.message || "Unknown error"));
      }
    };

    loadPreview();

    return () => {
      if (preview) {
        preview.dispose();
      }
    };
  }, [source, publicToken]);

  if (error) {
    return <div className="video-editor-error">{error}</div>;
  }

  return (
    <div className="video-editor-wrapper" style={{ width: "100%", position: "relative" }}>
      <div 
        ref={containerRef} 
        style={{ width: "100%", height: "400px", background: "#000", borderRadius: "8px", overflow: "hidden" }} 
      />
    </div>
  );
}
