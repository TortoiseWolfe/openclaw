/** Brand palette registry, typography, effects, and shared layout constants.
 *
 * Aesthetic direction: STEAMPUNK — Victorian industrial, brass & verdigris,
 * gaslight workshops, oxidized metal, aged parchment. Both brands are dark
 * themes with warm atmospheric gradients.
 */

export type Brand = "turtlewolfe" | "scripthammer";

export type ThemeColors = {
	bg: string;
	bgCard: string;
	accent: string;
	accentDim: string;
	text: string;
	textMuted: string;
	codeGreen: string;
	codeBlue: string;
	codeBg: string;
	overlay: string;
};

export type ThemeFonts = {
	heading: string;
	mono: string;
	display: string;
};

export type ThemeEffects = {
	bgGradient: string;
	accentGlow: string;
	accentTextShadow: string;
	cardShadow: string;
	codeBorderGlow: string;
};

export type ThemeBranding = {
	name: string;
	channel: string;
	tagline: string;
};

export type Theme = {
	colors: ThemeColors;
	fonts: ThemeFonts;
	effects: ThemeEffects;
	layout: typeof layout;
	branding: ThemeBranding;
};

export const layout = {
	padding: 60,
	width: 1920,
	height: 1080,
} as const;

/** TurtleWolfe — "Patina & Verdigris"
 *  Cool-toned dark theme. Oxidized bronze with green patina accents.
 *  Like an alchemist's workshop where copper instruments have aged beautifully. */
const turtlewolfe: Theme = {
	colors: {
		bg: "#0c1210",
		bgCard: "#162320",
		accent: "#5ab88a",
		accentDim: "#3d8a65",
		text: "#e8dcc8",
		textMuted: "#8a7a60",
		codeGreen: "#7eeaae",
		codeBlue: "#5a4a3a",
		codeBg: "#0a100d",
		overlay: "rgba(12, 18, 16, 0.88)",
	},
	fonts: {
		heading: "'Liberation Serif', Georgia, serif",
		mono: "'Liberation Mono', 'Courier New', monospace",
		display: "'Liberation Mono', 'Courier New', monospace",
	},
	effects: {
		bgGradient:
			"radial-gradient(ellipse at 25% 35%, #1a3028 0%, #0c1210 65%)",
		accentGlow: "0 0 28px rgba(90, 184, 138, 0.22)",
		accentTextShadow: "0 0 48px rgba(90, 184, 138, 0.28)",
		cardShadow:
			"0 4px 24px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(90, 184, 138, 0.08)",
		codeBorderGlow: "0 0 14px rgba(126, 234, 174, 0.12)",
	},
	layout,
	branding: {
		name: "TurtleWolfe",
		channel: "twitch.tv/turtlewolfe",
		tagline: "live coding & AI experiments",
	},
};

/** ScriptHammer — "Brass Workshop"
 *  Warm-toned dark theme. Polished brass, dark mahogany, gaslight amber.
 *  Like a Victorian inventor's forge where code is hammered into shape. */
const scripthammer: Theme = {
	colors: {
		bg: "#1a1410",
		bgCard: "#2a2218",
		accent: "#c8883c",
		accentDim: "#a06a28",
		text: "#ede0c8",
		textMuted: "#8a7a5a",
		codeGreen: "#dcc89a",
		codeBlue: "#3a4850",
		codeBg: "#141010",
		overlay: "rgba(26, 20, 16, 0.88)",
	},
	fonts: {
		heading: "'Liberation Serif', Georgia, serif",
		mono: "'Liberation Mono', 'Courier New', monospace",
		display: "'Liberation Mono', 'Courier New', monospace",
	},
	effects: {
		bgGradient:
			"radial-gradient(ellipse at 25% 35%, #2e2418 0%, #1a1410 65%)",
		accentGlow: "0 0 28px rgba(200, 136, 60, 0.22)",
		accentTextShadow: "0 0 48px rgba(200, 136, 60, 0.3)",
		cardShadow:
			"0 4px 24px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(200, 136, 60, 0.08)",
		codeBorderGlow: "0 0 14px rgba(200, 136, 60, 0.1)",
	},
	layout,
	branding: {
		name: "ScriptHammer",
		channel: "ScriptHammer.com",
		tagline: "AI-powered app factory",
	},
};

const themes: Record<Brand, Theme> = { turtlewolfe, scripthammer };

export function getTheme(brand: Brand = "turtlewolfe"): Theme {
	const theme = themes[brand];
	if (!theme) throw new Error(`Unknown brand: ${brand}`);
	return theme;
}

// Backward-compat default exports
export const colors = turtlewolfe.colors;
export const fonts = turtlewolfe.fonts;
