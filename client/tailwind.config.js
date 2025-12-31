/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                bg: '#1a1b26',
                text: '#c0caf5',
                primary: '#7aa2f7',
                secondary: '#bb9af7',
                hl: '#41a6b5',
            }
        },
    },
    plugins: [],
}
