import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { API_URL } from "../api";

const SITES: Record<string, { key: string; tenant: string }> = {
  skyline: { key: "pk_skyline_aria", tenant: "Skyline Realty" },
  brightsmile: { key: "pk_brightsmile_mia", tenant: "BrightSmile Dental Clinic" },
};

function useWidget(key: string | null) {
  useEffect(() => {
    if (!key || document.querySelector("script[data-agentgrid-demo]")) return;
    const s = document.createElement("script");
    s.src = `${API_URL}/widget.js`;
    s.async = true;
    s.dataset.agent = key;
    s.dataset.api = API_URL;
    s.dataset.agentgridDemo = "1";
    document.body.appendChild(s);
  }, [key]);
}

const openChat = (text?: string) => {
  const w = (window as any).AgentGrid;
  if (!w) return;
  if (text) w.send(text);
  else w.open();
};

export default function DemoSite() {
  const { slug = "" } = useParams();
  const [params] = useSearchParams();
  const site = SITES[slug];
  const key = site?.key || params.get("key");
  useWidget(key);
  useEffect(() => {
    document.title = site ? `${site.tenant} (demo website)` : "Agent preview";
  }, [site]);

  return (
    <div className="min-h-full bg-white">
      <div className="flex flex-wrap items-center justify-center gap-x-2 bg-[#172554] px-4 py-2 text-center text-[12.5px] text-[#F3EBDD]">
        <span>Demo website for the AgentGrid PoC. The chat bubble (bottom right) is a live AI agent from the {site?.tenant || "selected"} workspace.</span>
        <a href="/" className="font-semibold text-[#C19A5B] underline">Open the console</a>
      </div>
      {slug === "skyline" ? <Skyline /> : slug === "brightsmile" ? <BrightSmile /> : <Preview />}
    </div>
  );
}

function Preview() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center">
      <h1 className="font-serif text-4xl font-semibold text-[#172554]">Agent preview</h1>
      <p className="mt-4 text-[#4A5578]">This page embeds the chat widget for the agent key in the URL. Use the bubble in the corner.</p>
      <button onClick={() => openChat()} className="mt-8 rounded-full bg-[#172554] px-6 py-3 font-medium text-white">Open chat</button>
    </div>
  );
}

// ---------------------------------------------------------------- Skyline Realty (real estate)

const PROJECTS = [
  { name: "Orchid Heights", area: "Whitefield", from: "₹92 L", conf: "2 & 3 BHK", status: "Ready to move · Towers A, B", hue: "#C8963E" },
  { name: "Lakeview", area: "Hebbal", from: "₹2.15 Cr", conf: "3 & 4 BHK", status: "Possession June 2027", hue: "#5B7DA8" },
  { name: "Greens Villas", area: "Sarjapur Road", from: "₹3.4 Cr", conf: "4 BHK villas", status: "Phase 1 ready", hue: "#5E8C6A" },
];

function Skyline() {
  return (
    <div className="text-[#1E3A5F]" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2 font-serif text-xl font-semibold"><span className="inline-block size-7 rounded-md bg-[#1E3A5F]" style={{ clipPath: "polygon(0 100%, 0 40%, 30% 40%, 30% 10%, 60% 10%, 60% 55%, 100% 55%, 100% 100%)" }} /> Skyline Realty</div>
        <nav className="hidden gap-7 text-sm md:flex"><a href="#projects">Projects</a><a href="#why">Why Skyline</a><a href="#visit">Site visits</a></nav>
        <button onClick={() => openChat("Book a site visit")} className="rounded-full bg-[#1E3A5F] px-4 py-2 text-sm font-medium text-white">Book a visit</button>
      </header>
      <section className="relative overflow-hidden bg-[#1E3A5F] text-white">
        <svg className="absolute bottom-0 left-0 h-24 w-full opacity-[0.12]" viewBox="0 0 1200 200" preserveAspectRatio="none" aria-hidden>
          <path d="M0 200V120h60V70h50v50h40V40h70v80h50V90h40v30h60V20h80v100h40V60h60v60h50V80h70v40h40V30h60v90h50V70h60v50h40V50h70v70h40V100h60v100z" fill="#C8963E" />
        </svg>
        <div className="relative mx-auto grid max-w-6xl gap-10 px-6 py-20 md:grid-cols-2 md:py-28">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[#E3C38A]">Bengaluru · RERA registered</p>
            <h1 className="mt-4 font-serif text-5xl font-semibold leading-[1.05]">Homes that rise above the city.</h1>
            <p className="mt-5 max-w-md text-lg text-white/80">Apartments and villas in Whitefield, Hebbal and Sarjapur Road. Ask Aria anything about prices, possession or payment plans, any time.</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button onClick={() => openChat("Show me 3BHK options in Whitefield")} className="rounded-full bg-[#C8963E] px-6 py-3 font-semibold text-[#1E3A5F]">Find my home</button>
              <button onClick={() => openChat()} className="rounded-full border border-white/40 px-6 py-3 font-medium">Chat with Aria</button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 self-end">
            {[["3,200+", "families moved in"], ["14", "projects delivered"], ["8.35%", "home loans from"], ["4 min", "to the metro"]].map(([n, l]) => (
              <div key={l} className="rounded-2xl bg-white/10 p-5 backdrop-blur"><div className="font-serif text-3xl font-semibold">{n}</div><div className="text-sm text-white/70">{l}</div></div>
            ))}
          </div>
        </div>
      </section>
      <section id="projects" className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="font-serif text-3xl font-semibold">Current projects</h2>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {PROJECTS.map((p) => (
            <article key={p.name} className="overflow-hidden rounded-2xl border border-[#E5E1D8] bg-white shadow-sm">
              <div className="h-40" style={{ background: `linear-gradient(135deg, ${p.hue}, #1E3A5F)` }} />
              <div className="p-5">
                <div className="text-xs font-semibold uppercase tracking-wide text-[#8A6A2F]">{p.area}</div>
                <h3 className="mt-1 font-serif text-xl font-semibold">{p.name}</h3>
                <p className="mt-1 text-sm text-[#4A5578]">{p.conf} · {p.status}</p>
                <div className="mt-4 flex items-center justify-between">
                  <span className="font-semibold">From {p.from}</span>
                  <button onClick={() => openChat(`Tell me about ${p.name} pricing and availability`)} className="text-sm font-medium underline">Ask Aria</button>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
      <section id="why" className="bg-[#F7F3EC]">
        <div className="mx-auto grid max-w-6xl gap-8 px-6 py-16 md:grid-cols-3">
          {[["Transparent pricing", "All-inclusive prices with parking. No surprises at registration."], ["Flexible plans", "Construction-linked, down payment with 4% off, or subvention on Lakeview."], ["Loan desk", "Pre-approved with SBI, HDFC, ICICI, Axis and LIC HFL. We handle the paperwork."]].map(([t, d]) => (
            <div key={t}><h3 className="font-serif text-xl font-semibold">{t}</h3><p className="mt-2 text-[#4A5578]">{d}</p></div>
          ))}
        </div>
      </section>
      <section id="visit" className="mx-auto max-w-6xl px-6 py-20 text-center">
        <h2 className="font-serif text-3xl font-semibold">See it for yourself</h2>
        <p className="mx-auto mt-3 max-w-xl text-[#4A5578]">Site visits Monday to Saturday with free pick-up within 15 km. Aria can book one in under a minute.</p>
        <button onClick={() => openChat("I'd like to book a site visit")} className="mt-7 rounded-full bg-[#1E3A5F] px-7 py-3 font-semibold text-white">Book a site visit</button>
      </section>
      <footer className="border-t border-[#E5E1D8] py-8 text-center text-sm text-[#4A5578]">Skyline Experience Centre, Indiranagar, Bengaluru · Fictional company for demonstration</footer>
    </div>
  );
}

// ---------------------------------------------------------------- BrightSmile (healthcare clinic)

const TREATMENTS = [
  ["Check-up & X-ray", "₹800", "Full exam and a clear plan"],
  ["Cleaning & polishing", "₹1,500", "Every 6 months keeps gums healthy"],
  ["Teeth whitening", "₹12,000", "60 minutes, lasts up to 2 years"],
  ["Clear aligners", "from ₹1.2 L", "Free 3D scan assessment"],
  ["Root canal", "from ₹6,500", "Single sitting where possible"],
  ["Implants", "from ₹38,000", "Permanent tooth replacement"],
];

function BrightSmile() {
  return (
    <div className="text-[#12343B]" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2 font-serif text-xl font-semibold"><span className="flex size-8 items-center justify-center rounded-full bg-[#0E5E6F] text-white">✦</span> BrightSmile</div>
        <nav className="hidden gap-7 text-sm md:flex"><a href="#treatments">Treatments</a><a href="#team">Our dentists</a><a href="#visit">Visit us</a></nav>
        <button onClick={() => openChat("Book a check-up")} className="rounded-full bg-[#0E5E6F] px-4 py-2 text-sm font-medium text-white">Book appointment</button>
      </header>
      <section className="bg-gradient-to-br from-[#E6F2F1] to-[#FFF6E8]">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-6 py-20 md:grid-cols-[1.2fr_1fr]">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[#0E5E6F]">Koramangala · Since 2012</p>
            <h1 className="mt-4 font-serif text-5xl font-semibold leading-[1.05]">Gentle dentistry for the whole family.</h1>
            <p className="mt-5 max-w-md text-lg text-[#3E5C61]">Clear prices, careful hands and appointments that run on time. Mia can answer questions and book you in, day or night.</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button onClick={() => openChat("I'd like to book a check-up")} className="rounded-full bg-[#0E5E6F] px-6 py-3 font-semibold text-white">Book a check-up</button>
              <button onClick={() => openChat("How much is teeth whitening?")} className="rounded-full border border-[#0E5E6F]/40 px-6 py-3 font-medium">Ask about prices</button>
            </div>
          </div>
          <div className="rounded-3xl bg-white p-6 shadow-sm">
            <h2 className="font-semibold">Opening hours</h2>
            <dl className="mt-3 space-y-2 text-sm">
              {[["Mon to Fri", "9:00 AM to 6:00 PM"], ["Saturday", "9:00 AM to 2:00 PM"], ["Sunday", "Closed"]].map(([d, h]) => <div key={d} className="flex justify-between"><dt className="text-[#3E5C61]">{d}</dt><dd className="font-medium">{h}</dd></div>)}
            </dl>
            <p className="mt-4 rounded-xl bg-[#FFF6E8] p-3 text-sm text-[#7A4E00]">In pain or swelling? Mia will connect you to our front desk straight away.</p>
          </div>
        </div>
      </section>
      <section id="treatments" className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="font-serif text-3xl font-semibold">Treatments and prices</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TREATMENTS.map(([t, p, d]) => (
            <button key={t} onClick={() => openChat(`Tell me about ${t.toLowerCase()}`)} className="rounded-2xl border border-[#DCE8E7] bg-white p-5 text-left transition hover:border-[#0E5E6F]/40 hover:shadow-sm">
              <div className="flex items-baseline justify-between gap-3"><h3 className="font-semibold">{t}</h3><span className="font-serif text-lg font-semibold text-[#0E5E6F]">{p}</span></div>
              <p className="mt-1 text-sm text-[#3E5C61]">{d}</p>
            </button>
          ))}
        </div>
      </section>
      <section id="team" className="bg-[#F4F8F8]">
        <div className="mx-auto grid max-w-6xl gap-6 px-6 py-16 md:grid-cols-3">
          {[["Dr. Kavya Rao", "Orthodontics: braces and aligners"], ["Dr. Arjun Menon", "Endodontics: root canals"], ["Dr. Sneha Iyer", "Family and cosmetic dentistry"]].map(([n, r]) => (
            <div key={n} className="rounded-2xl bg-white p-5"><div className="flex size-12 items-center justify-center rounded-full bg-[#0E5E6F] font-serif text-lg text-white">{n.split(" ")[1].charAt(0)}</div><h3 className="mt-3 font-semibold">{n}</h3><p className="text-sm text-[#3E5C61]">{r}</p></div>
          ))}
        </div>
      </section>
      <section id="visit" className="mx-auto max-w-6xl px-6 py-16 text-center">
        <h2 className="font-serif text-3xl font-semibold">2nd Floor, Lotus Plaza, Koramangala 4th Block</h2>
        <p className="mt-2 text-[#3E5C61]">Basement parking available · UPI, cards and no-cost EMI</p>
      </section>
      <footer className="border-t border-[#DCE8E7] py-8 text-center text-sm text-[#3E5C61]">Fictional clinic for demonstration. Not medical advice.</footer>
    </div>
  );
}
