"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

export default function Home() {
  const [city, setCity] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const [mistralText, setMistralText] = useState<string | null>(null);
  const [routeData, setRouteData] = useState<any>(null);


  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapContainerRef = useRef<HTMLDivElement | null>(null);

  async function callMistral(prompt: string) {
    const res = await fetch("http://localhost:8000/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ prompt }),
    });

    if (!res.ok) {
      throw new Error("Failed to call backend");
    }

    return res.json();
  }

  


  async function fetchPlan() {
    if (!city) return;

    setLoading(true);

    try {
      // 1. Call your plan-generating backend
      const res = await fetch(`http://localhost:8000/plan/${city}/120`);
      const planJson = await res.json();
      setRouteData(planJson);

      // 2. Then call Mistral to turn the JSON into text
      const prompt = `
        Convert the following JSON route into a human-readable tour description.
        JSON: ${JSON.stringify(planJson)}
      `;
      const mistralRes = await callMistral(prompt);
      setMistralText(mistralRes.answer);

      // 3. Draw route
      if (planJson.route && planJson.route.polyline) {
        const geojson = {
          type: "Feature",
          geometry: {
            type: "LineString",
            coordinates: planJson.route.polyline.map((p: any) => [p[1], p[0]])
          },
          properties: {}
        };

        drawRoute(geojson);
      }

      } catch (err) {
        console.error(err);
        setRouteData({ error: "backend error" });
    }

    setLoading(false);
  }


  // Initialize MapLibre (only once)
  useEffect(() => {
    if (mapRef.current) return; // already created

    mapRef.current = new maplibregl.Map({
      container: mapContainerRef.current!,
      style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
      center: [0, 0],
      zoom: 2,
    });
  }, []);

  function drawRoute(geojson: any) {
    const map = mapRef.current;
    if (!map) return;

    // Remove previous route layer if exists
    if (map.getSource("route")) {
      map.removeLayer("route");
      map.removeSource("route");
    }

    map.addSource("route", {
      type: "geojson",
      data: geojson,
    });

    map.addLayer({
      id: "route",
      type: "line",
      source: "route",
      paint: {
        "line-color": "#ff0000",
        "line-width": 4,
      },
    });

    // Fit map to route bounds
    const bounds = new maplibregl.LngLatBounds();

    geojson.geometry.coordinates.forEach((c: any) =>
      bounds.extend([c[0], c[1]])
    );

    map.fitBounds(bounds, { padding: 40 });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", padding: 20, gap: 20 }}>
      <h1 style={{ fontSize: "24px", fontWeight: "bold" }}>MarcheRoute MVP</h1>

      <div>
        <input
          type="text"
          placeholder="Enter a city…"
          value={city}
          onChange={(e) => setCity(e.target.value)}
          style={{
            padding: 8,
            marginRight: 10,
            width: 240,
            borderRadius: 4,
            border: "1px solid #ccc",
          }}
        />
        <button
          onClick={fetchPlan}
          style={{
            padding: "8px 16px",
            background: "#000",
            color: "#fff",
            borderRadius: 4,
          }}
        >
          Generate route
        </button>
      </div>

      {loading && <p>Loading…</p>}

      {mistralText && (
        <pre
          style={{
            marginTop: 10,
            background: "#f2f2f2",
            color: "#231e1eff",
            padding: 10,
            borderRadius: 8,
            maxHeight: 200,
            overflow: "auto",
          }}
        >
          {typeof mistralText === "string"
            ? mistralText
            : JSON.stringify(mistralText, null, 2)}
        </pre>
      )}

      {/* {routeData && (
        <pre
          style={{
            marginTop: 10,
            background: "#f2f2f2",
            color: "#231e1eff",
            padding: 10,
            borderRadius: 8,
            maxHeight: 200,
            overflow: "auto",
          }}
        >
          {typeof routeData === "string"
            ? routeData
            : JSON.stringify(routeData, null, 2)}
        </pre>
      )} */}



      {/* Map container */}
      <div
        ref={mapContainerRef}
        style={{
          height: "500px",
          width: "100%",
          borderRadius: "8px",
          border: "1px solid #aaa",
        }}
      ></div>
    </div>
  );
}
