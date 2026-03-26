import type { Tool, ToolResult } from '@memgrafter/flatagents';

const WEATHER_DATA: Record<string, { temp_f: number; condition: string }> = {
  tokyo: { temp_f: 68, condition: 'partly cloudy' },
  'new york': { temp_f: 55, condition: 'overcast' },
  london: { temp_f: 50, condition: 'rainy' },
  'san francisco': { temp_f: 62, condition: 'foggy' },
  paris: { temp_f: 58, condition: 'sunny' },
  sydney: { temp_f: 75, condition: 'clear skies' },
};

const TIMEZONE_OFFSETS: Record<string, number> = {
  utc: 0,
  'us/eastern': -5,
  'us/central': -6,
  'us/mountain': -7,
  'us/pacific': -8,
  'europe/london': 0,
  'europe/paris': 1,
  'europe/berlin': 1,
  'asia/tokyo': 9,
  'asia/shanghai': 8,
  'australia/sydney': 11,
};

async function getWeather(_toolCallId: string, args: Record<string, any>): Promise<ToolResult> {
  const city = String(args.city ?? '').trim().toLowerCase();
  const data = WEATHER_DATA[city];

  if (!data) {
    const known = Object.keys(WEATHER_DATA).sort().join(', ');
    return {
      content: `No weather data for '${city}'. Known cities: ${known}`,
      is_error: true,
    };
  }

  return {
    content: `${data.temp_f}°F and ${data.condition} in ${toTitle(city)}`,
    is_error: false,
  };
}

async function getTime(_toolCallId: string, args: Record<string, any>): Promise<ToolResult> {
  const tzName = String(args.timezone ?? 'utc').trim().toLowerCase();
  const offset = TIMEZONE_OFFSETS[tzName];

  if (offset === undefined) {
    const known = Object.keys(TIMEZONE_OFFSETS).sort().join(', ');
    return {
      content: `Unknown timezone '${tzName}'. Known timezones: ${known}`,
      is_error: true,
    };
  }

  const nowUtc = new Date();
  const local = new Date(nowUtc.getTime() + (offset * 60 * 60 * 1000));
  const formatted = local.toISOString().replace('T', ' ').slice(0, 19);
  return {
    content: `${formatted} (UTC${offset >= 0 ? '+' : ''}${offset}; ${tzName})`,
    is_error: false,
  };
}

function toTitle(value: string): string {
  return value
    .split(' ')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export const ALL_TOOLS: Tool[] = [
  {
    name: 'get_weather',
    description: 'Get the current weather for a city.',
    parameters: {
      type: 'object',
      properties: {
        city: {
          type: 'string',
          description: "City name, e.g. 'Tokyo' or 'New York'",
        },
      },
      required: ['city'],
    },
    execute: getWeather,
  },
  {
    name: 'get_time',
    description: 'Get the current time in a given timezone.',
    parameters: {
      type: 'object',
      properties: {
        timezone: {
          type: 'string',
          description: "Timezone identifier, e.g. 'UTC', 'US/Pacific', 'Asia/Tokyo', 'Europe/London'",
        },
      },
      required: ['timezone'],
    },
    execute: getTime,
  },
];
