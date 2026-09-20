import { useEffect, useRef, useState } from 'react';
import { token } from '../lib/token';
import { buildEdges, scatterPoints, seededRandom, selectConnected, type Edge } from './particles';

/**
 * Boot sequence: datapoints scatter, a subset wires itself together, the links
 * let go, and the whole field then drifts forward past the viewer as the
 * workspace comes through. Points that never join the mesh stay unconnected
 * throughout.
 *
 * Phase timings in ms from start. Deliberately brief — a splash that outstays
 * its welcome is worse than none.
 */
const PHASES = {
  emerge: 420, // points fade in across the field
  connect: 1350, // mesh draws between neighbours — this is the loading buffer
  release: 1800, // links let go; the field is unconnected points again
  enter: 2300, // field pushes forward and clears; the page is revealed through it
} as const;

/** Overlay fade runs *during* the push, so the page arrives as part of the same
 *  motion rather than after it. */
const ENTER_FADE_MS = 640;

/** How far the field expands on the way in. Enough to read as forward motion,
 *  far short of a blast. */
const ENTER_SCALE = 0.26;

const PARTICLE_COUNT = 620;

/** Only part of the field ever joins the mesh. The rest stay unconnected
 *  throughout, so it reads as real scattered data — some points correlate,
 *  some are just noise — rather than one uniform web. */
const CONNECTED_FRACTION = 0.6;

interface Particle {
  ox: number; // scattered origin
  oy: number;
  x: number;
  y: number;
}

const easeInOutQuad = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
const clamp01 = (t: number) => Math.min(1, Math.max(0, t));

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  } catch {
    return false;
  }
}

export function SplashScreen({ onComplete }: { onComplete: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const doneRef = useRef(false);
  const [leaving, setLeaving] = useState(false);
  // Set when the canvas cannot animate (jsdom, reduced motion, blocked canvas).
  const [staticFallback, setStaticFallback] = useState(false);

  // One exit path for every route out: sequence finished, skipped, or fallback.
  const finish = useRef((fadeMs = ENTER_FADE_MS) => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    window.setTimeout(onComplete, fadeMs);
  }).current;

  useEffect(() => {
    if (prefersReducedMotion()) {
      setStaticFallback(true);
      const timer = window.setTimeout(() => finish(300), 400);
      return () => window.clearTimeout(timer);
    }

    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      setStaticFallback(true);
      const timer = window.setTimeout(() => finish(300), 650);
      return () => window.clearTimeout(timer);
    }

    const width = canvas.clientWidth || window.innerWidth || 1024;
    const height = canvas.clientHeight || window.innerHeight || 640;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);

    const random = seededRandom(0x51ab);
    const scattered = scatterPoints(PARTICLE_COUNT, width, height, random);

    // Only a subset participates; edges are fixed to the scattered layout, so
    // the mesh travels with the field rather than being rebuilt every frame.
    const connectedIndices = selectConnected(scattered.length, CONNECTED_FRACTION, random);
    const connectedPoints = connectedIndices.map((index) => scattered[index]);
    const edges: Edge[] = buildEdges(connectedPoints, Math.min(width, height) * 0.13, 2).map(
      ({ a, b }) => ({ a: connectedIndices[a], b: connectedIndices[b] }),
    );

    const particles: Particle[] = scattered.map((point) => ({
      ox: point.x,
      oy: point.y,
      x: point.x,
      y: point.y,
    }));

    // Canvas needs literal colours; read them off the live tokens, so the
    // field is the accent and the links are the muted ink of whatever theme
    // is active when the sequence starts.
    const palette = {
      dot: token(document.documentElement, '--primary'),
      edge: token(document.documentElement, '--muted-foreground'),
    };
    let raf = 0;
    let entering = false;
    const start = performance.now();

    const render = (now: number) => {
      const elapsed = now - start;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const emerge = clamp01(elapsed / PHASES.emerge);
      const connect = clamp01(
        (elapsed - PHASES.emerge * 0.7) / (PHASES.connect - PHASES.emerge * 0.7),
      );
      // Links let go before the field moves, so the disconnect is its own beat
      // rather than something lost inside the exit fade.
      const release = clamp01((elapsed - PHASES.connect) / (PHASES.release - PHASES.connect));
      const enter = easeInOutQuad(
        clamp01((elapsed - PHASES.release) / (PHASES.enter - PHASES.release)),
      );

      // The field expands outward from the centre: it passes the viewer rather
      // than collapsing away, which is what reads as moving *into* the page.
      const scale = 1 + enter * ENTER_SCALE;
      for (const particle of particles) {
        particle.x = width / 2 + (particle.ox - width / 2) * scale;
        particle.y = height / 2 + (particle.oy - height / 2) * scale;
      }

      const fade = 1 - enter;

      // Mesh: revealed progressively, then carried out with the field.
      const revealed = Math.floor(edges.length * connect);
      const reach = Math.min(width, height) * 0.22;
      ctx.lineWidth = 1;
      ctx.strokeStyle = palette.edge;
      for (let i = 0; i < revealed; i += 1) {
        const a = particles[edges[i].a];
        const b = particles[edges[i].b];
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        if (distance > reach) continue;
        ctx.globalAlpha = (1 - distance / reach) * 0.5 * emerge * (1 - release);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      ctx.fillStyle = palette.dot;
      ctx.globalAlpha = emerge * fade;
      const radius = 1.5 + enter * 0.8;
      for (const particle of particles) {
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }

      // Begin the reveal as the push starts, so the page comes forward through
      // the field rather than after it has gone.
      if (!entering && elapsed >= PHASES.release) {
        entering = true;
        finish();
      }
      if (elapsed >= PHASES.enter + 100) return; // overlay is already fading

      raf = window.requestAnimationFrame(render);
    };

    raf = window.requestAnimationFrame(render);
    return () => window.cancelAnimationFrame(raf);
    // Runs once: restarting the boot sequence on a theme toggle would be
    // jarring, and it is over within seconds anyway.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      role="status"
      aria-label="Loading QuantLab"
      data-testid="splash-screen"
      onClick={() => finish(260)}
      className={`fixed inset-0 z-50 bg-background transition-opacity duration-[640ms] ${
        leaving ? 'pointer-events-none opacity-0' : 'opacity-100'
      }`}
    >
      {staticFallback ? (
        <div data-testid="splash-static" className="flex h-full w-full items-center justify-center">
          <span className="h-2 w-2 border border-primary bg-primary/20" />
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          data-testid="splash-canvas"
          aria-hidden="true"
          className="h-full w-full"
        />
      )}

      <button
        type="button"
        onClick={() => finish(260)}
        data-testid="splash-skip"
        className="absolute bottom-8 left-1/2 -translate-x-1/2 rounded-sm px-3 py-1 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        Skip
      </button>
    </div>
  );
}
