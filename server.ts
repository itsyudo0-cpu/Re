import express from 'express';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { GoogleGenAI, Type } from '@google/genai';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ai = new GoogleGenAI({
  apiKey: process.env.GEMINI_API_KEY,
  httpOptions: {
    headers: {
      'User-Agent': 'aistudio-build',
    },
  },
});

const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-3.8-flash';

const BOT_FILE_MANIFEST = [
  {
    path: 'main.py',
    category: 'Core Architecture',
    description: 'Pyrogram v2.x Client entry point, plugin loader, Telegraph & Motor initialization',
    language: 'python',
  },
  {
    path: 'config.py',
    category: 'Core Architecture',
    description: 'Environment & configuration loader (API_ID, MONGO_URI, GEMINI_API_KEY, FSUB, LOG_CHANNEL_ID, UPI)',
    language: 'python',
  },
  {
    path: 'database.py',
    category: 'Core Architecture',
    description: 'Motor async MongoDB layer for users, daily quotas, auto-expiry, payment proofs & stats',
    language: 'python',
  },
  {
    path: 'utils/fsub.py',
    category: 'Middleware & Utilities',
    description: 'Force Subscribe (FSUB) decorator & channel membership verifier with Refresh callback',
    language: 'python',
  },
  {
    path: 'utils/logger.py',
    category: 'Middleware & Utilities',
    description: 'LOG_CHANNEL_ID activity logger & upload-first PDF delivery pipeline',
    language: 'python',
  },
  {
    path: 'utils/extractor.py',
    category: 'Middleware & Utilities',
    description: 'Trafilatura/Readability scraper, YouTube Transcript API, Telegraph IV & Gemini AI Summarizer',
    language: 'python',
  },
  {
    path: 'plugins/start.py',
    category: 'Pyrogram Plugins',
    description: '/start command with custom banner, inline navigation, /myaccount & FSUB refresh callback',
    language: 'python',
  },
  {
    path: 'plugins/reader.py',
    category: 'Pyrogram Plugins',
    description: 'PM direct URL handler, Group /read & /summary commands, and [📥 Export Clean PDF] callback',
    language: 'python',
  },
  {
    path: 'plugins/inline.py',
    category: 'Pyrogram Plugins',
    description: 'Inline Mode (@botusername <URL>) on-the-fly Instant View & AI Summary card generator',
    language: 'python',
  },
  {
    path: 'plugins/premium.py',
    category: 'Pyrogram Plugins',
    description: 'Manual UPI QR code generator, UTR/Screenshot proof handler, and Admin [Approve/Reject] workflow',
    language: 'python',
  },
  {
    path: 'plugins/admin.py',
    category: 'Pyrogram Plugins',
    description: 'Admin controls: /stats, /broadcast (with FloodWait handling), /addpremium, /removepremium',
    language: 'python',
  },
  {
    path: 'requirements.txt',
    category: 'Deployment & Config',
    description: 'Pinned production Python dependencies (pyrofork, motor, google-generativeai, trafilatura, weasyprint)',
    language: 'text',
  },
  {
    path: '.env.example',
    category: 'Deployment & Config',
    description: 'Template environment variables for Telegram API, MongoDB, Gemini, FSUB, Log Channel & UPI',
    language: 'ini',
  },
  {
    path: 'Dockerfile',
    category: 'Deployment & Config',
    description: 'Production Python 3.11 container with Cairo/Pango libraries for WeasyPrint PDF rendering',
    language: 'dockerfile',
  },
];

function extractYoutubeId(url: string): string | null {
  const regex = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/i;
  const match = url.match(regex);
  return match ? match[1] : null;
}

function stripHtmlToCleanText(html: string): { title: string; text: string } {
  const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const rawTitle = titleMatch ? titleMatch[1].replace(/\s+/g, ' ').trim() : '';

  const cleaned = html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<nav[\s\S]*?<\/nav>/gi, ' ')
    .replace(/<footer[\s\S]*?<\/footer>/gi, ' ')
    .replace(/<header[\s\S]*?<\/header>/gi, ' ')
    .replace(/<svg[\s\S]*?<\/svg>/gi, ' ')
    .replace(/<\/?(p|div|h1|h2|h3|h4|li|blockquote|br)[^>]*>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return { title: rawTitle, text: cleaned };
}

async function startServer() {
  const app = express();
  // Render (and most hosts) provide the port via the PORT env variable
  const PORT = Number(process.env.PORT) || 3000;

  app.use(express.json({ limit: '2mb' }));

  // Simple health check (useful for Render / uptime monitors)
  app.get('/health', (_req, res) => {
    res.json({ ok: true });
  });

  // 1. Return all Python Bot files from /bot directory
  app.get('/api/bot-files', async (_req, res) => {
    try {
      const botDir = path.resolve(__dirname, 'bot');
      const files = await Promise.all(
        BOT_FILE_MANIFEST.map(async (item) => {
          const fullPath = path.join(botDir, item.path);
          const content = await fs.readFile(fullPath, 'utf-8');
          return {
            ...item,
            content,
            lines: content.split('\n').length,
          };
        })
      );
      res.json({ files });
    } catch (error: any) {
      console.error('Error loading bot files:', error);
      res.status(500).json({ error: error?.message || 'Failed to read bot files' });
    }
  });

  // 2. Live URL / YouTube Extraction & Gemini AI Summarization Endpoint
  app.post('/api/process-url', async (req, res) => {
    const { url } = req.body as { url?: string };
    if (!url || typeof url !== 'string' || !/^https?:\/\//i.test(url.trim())) {
      res.status(400).json({ error: 'Please provide a valid HTTP/HTTPS URL.' });
      return;
    }

    const targetUrl = url.trim();
    const ytId = extractYoutubeId(targetUrl);
    const isYoutube = Boolean(ytId);

    let fetchedTitle = '';
    let fetchedAuthor = '';
    let extractedContent = '';

    try {
      if (isYoutube && ytId) {
        const oembedUrl = `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=${ytId}&format=json`;
        const oembedResp = await fetch(oembedUrl);
        if (oembedResp.ok) {
          const oembedData = (await oembedResp.json()) as any;
          fetchedTitle = oembedData.title || `YouTube Video (${ytId})`;
          fetchedAuthor = oembedData.author_name || 'YouTube Channel';
        }
        // Also fetch video page for description context
        const pageResp = await fetch(`https://www.youtube.com/watch?v=${ytId}`, {
          headers: { 'User-Agent': 'Mozilla/5.0 (compatible; CleanReaderBot/2.0)' },
        });
        if (pageResp.ok) {
          const rawHtml = await pageResp.text();
          const descMatch = rawHtml.match(/"shortDescription":"((?:[^"\\]|\\.)*)"/);
          if (descMatch && descMatch[1]) {
            extractedContent = descMatch[1].replace(/\\n/g, '\n').slice(0, 12000);
          }
        }
      } else {
        const parsedHost = new URL(targetUrl).hostname.replace(/^www\./, '');
        fetchedAuthor = parsedHost;
        const pageResp = await fetch(targetUrl, {
          headers: {
            'User-Agent':
              'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36',
            Accept: 'text/html,application/xhtml+xml',
          },
          signal: AbortSignal.timeout(12000),
        });
        if (pageResp.ok) {
          const rawHtml = await pageResp.text();
          const parsed = stripHtmlToCleanText(rawHtml);
          fetchedTitle = parsed.title;
          extractedContent = parsed.text.slice(0, 22000);
        }
      }
    } catch (fetchErr) {
      // If target site blocks direct fetch, Gemini still synthesizes based on URL & context
      console.warn('Direct fetch fallback for URL:', targetUrl, fetchErr);
    }

    try {
      const prompt = isYoutube
        ? `Analyze this YouTube video for the CleanReader & Media Summarizer Telegram Bot.
URL: ${targetUrl}
Detected Video Title: ${fetchedTitle || 'Infer from URL/context'}
Channel: ${fetchedAuthor || 'YouTube Creator'}
Extracted Description/Transcript Snippet:
${extractedContent || 'Not directly accessible; infer comprehensive technical/educational breakdown from URL and metadata.'}

Generate:
1. A clean, accurate title and author/channel name.
2. A crisp 3-sentence TL;DR executive summary.
3. 5 high-signal key bullet points.
4. 4 to 5 realistic chronological timestamp breakdowns (e.g. "00:00 - Introduction & problem statement").
5. 4 clean, well-structured paragraphs representing the distraction-free reader transcript summary.`
        : `Analyze this web article for the CleanReader & Media Summarizer Telegram Bot.
URL: ${targetUrl}
Detected Page Title: ${fetchedTitle || 'Infer from URL'}
Source Domain: ${fetchedAuthor || new URL(targetUrl).hostname}
Scraped Text Content:
${extractedContent || 'Direct scrape restricted; synthesize accurate, high-signal reader content from URL context.'}

Generate:
1. The clean article title and author/publication name.
2. A crisp 3-sentence TL;DR summary.
3. 5 key bullet points capturing the core takeaways.
4. 4 to 6 clean, distraction-free reader paragraphs stripped of ads and navigation clutter.`;

      const response = await ai.models.generateContent({
        model: GEMINI_MODEL,
        contents: prompt,
        config: {
          responseMimeType: 'application/json',
          responseSchema: {
            type: Type.OBJECT,
            properties: {
              title: { type: Type.STRING },
              authorOrChannel: { type: Type.STRING },
              tldrThreeSentences: { type: Type.STRING },
              bulletPoints: {
                type: Type.ARRAY,
                items: { type: Type.STRING },
              },
              timestampsBreakdown: {
                type: Type.ARRAY,
                items: { type: Type.STRING },
              },
              cleanParagraphs: {
                type: Type.ARRAY,
                items: { type: Type.STRING },
              },
              estimatedReadMinutes: { type: Type.INTEGER },
            },
            required: [
              'title',
              'authorOrChannel',
              'tldrThreeSentences',
              'bulletPoints',
              'cleanParagraphs',
              'estimatedReadMinutes',
            ],
          },
        },
      });

      const parsedJson = JSON.parse((response.text ?? '{}').trim());
      const title = parsedJson.title || fetchedTitle || 'Extracted Article';
      const slug = title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
        .slice(0, 42);
      const dateSuffix = new Date().toISOString().slice(5, 10);
      const telegraphUrl = `https://telegra.ph/${slug || 'CleanReader'}-${dateSuffix}`;

      const cleanParagraphs: string[] = Array.isArray(parsedJson.cleanParagraphs)
        ? parsedJson.cleanParagraphs
        : [];
      const wordCount =
        extractedContent.split(/\s+/).filter(Boolean).length ||
        cleanParagraphs.join(' ').split(/\s+/).filter(Boolean).length ||
        450;

      res.json({
        url: targetUrl,
        isYoutube,
        title,
        authorOrChannel: parsedJson.authorOrChannel || fetchedAuthor || 'CleanReader Source',
        tldrThreeSentences: parsedJson.tldrThreeSentences || '',
        bulletPoints: parsedJson.bulletPoints || [],
        timestampsBreakdown: isYoutube ? parsedJson.timestampsBreakdown || [] : [],
        cleanParagraphs,
        estimatedReadMinutes: parsedJson.estimatedReadMinutes || Math.max(2, Math.ceil(wordCount / 200)),
        wordCount,
        telegraphUrl,
      });
    } catch (error: any) {
      console.error('Gemini API error in /api/process-url:', error);
      res.status(500).json({
        error: error?.message || 'Failed to summarize URL with Gemini API.',
      });
    }
  });

  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    // Express 4 syntax ('*all' is Express 5 only)
    app.get('*', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`CleanReader Architect Server running on port ${PORT}`);
  });
}

startServer();
