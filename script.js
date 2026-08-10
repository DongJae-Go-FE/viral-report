// ── 이미지 placeholder 처리 ──
// images/ 폴더에 지정된 파일명으로 이미지를 넣으면 자동 표시되고,
// 파일이 없으면 파일명이 안내된 placeholder가 나타납니다.
document.querySelectorAll('.shot img').forEach((img) => {
  const markMissing = () => {
    const shot = img.closest('.shot');
    shot.classList.add('missing');
    const caption = shot.querySelector('figcaption');
    if (caption && !caption.querySelector('.shot-hint')) {
      const hint = document.createElement('span');
      hint.className = 'shot-hint';
      hint.textContent = '→ ' + img.getAttribute('src') + ' 파일을 넣으면 표시됩니다';
      caption.appendChild(hint);
    }
  };
  if (img.complete && img.naturalWidth === 0) markMissing();
  else img.addEventListener('error', markMissing);
});

// ── 라이트박스: 스크린샷 클릭 시 크게 보기 ──
document.addEventListener('click', (e) => {
  const img = e.target.closest('.shot:not(.missing) img');
  if (!img) return;
  const overlay = document.createElement('div');
  overlay.className = 'lightbox';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-label', img.alt || '스크린샷 확대 보기');
  const full = document.createElement('img');
  full.src = img.src;
  full.alt = img.alt;
  const hint = document.createElement('span');
  hint.className = 'lightbox-hint';
  hint.textContent = '클릭하거나 ESC를 눌러 닫기';
  overlay.append(full, hint);
  const close = () => {
    overlay.remove();
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (ev) => { if (ev.key === 'Escape') close(); };
  overlay.addEventListener('click', close);
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
});

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// ── 조회수 바: 화면에 들어올 때 채워지는 애니메이션 ──
if (!reduceMotion && 'IntersectionObserver' in window) {
  const bars = document.querySelectorAll('.report-table .bar');
  bars.forEach((b) => b.classList.add('pre'));
  const barObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.remove('pre');
          barObserver.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.4 }
  );
  bars.forEach((b) => barObserver.observe(b));
}

// ── 핵심 지표 카운트업 ──
if (!reduceMotion && 'IntersectionObserver' in window) {
  const fmt = new Intl.NumberFormat('ko-KR');
  const animate = (el) => {
    const target = Number(el.dataset.count);
    const duration = 900;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = fmt.format(Math.round(target * eased));
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };
  const countObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          animate(entry.target);
          countObserver.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.6 }
  );
  document.querySelectorAll('.count').forEach((el) => countObserver.observe(el));
}

// ── 목차 스크롤 스파이 ──
const tocLinks = document.querySelectorAll('.toc a');
const sections = Array.from(tocLinks)
  .map((a) => document.querySelector(a.getAttribute('href')))
  .filter(Boolean);

if ('IntersectionObserver' in window && sections.length) {
  const setActive = (id) => {
    tocLinks.forEach((a) =>
      a.classList.toggle('active', a.getAttribute('href') === '#' + id)
    );
  };
  const spy = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible.length) setActive(visible[0].target.id);
    },
    { rootMargin: '-15% 0px -65% 0px' }
  );
  sections.forEach((s) => spy.observe(s));
}
