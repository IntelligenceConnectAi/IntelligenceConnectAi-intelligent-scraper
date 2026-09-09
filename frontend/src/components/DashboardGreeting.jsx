// Plain (no panel/border) welcome header for the Dashboard — time-of-day
// greeting by the client's own device clock, plus a quote picked at random
// when the Dashboard mounts (once per visit/session, not on every re-render).
// Quotes are real, attributed lines from business/entrepreneurship figures,
// cross-checked against multiple sources — commonly-misattributed ones
// (fake Einstein/Ford/Drucker lines that circulate online) were deliberately
// left out.
import { useState } from "react";

const QUOTES = [
  { text: "Failure is success if we learn from it.", author: "Malcolm Forbes" },
  { text: "If you don't drive your business, you will be driven out of business.", author: "B. C. Forbes" },
  { text: "Always deliver more than expected.", author: "Larry Page" },
  { text: "If your actions inspire others to dream more, learn more, do more and become more, you are a leader.", author: "John Quincy Adams" },
  { text: "Success is not final; failure is not fatal: it is the courage to continue that counts.", author: "Winston Churchill" },
  { text: "If you're passionate about something and you work hard, then I think you will be successful.", author: "Pierre Omidyar" },
  { text: "I've failed over and over and over again in my life, and that is why I succeed.", author: "Michael Jordan" },
  { text: "It's fine to celebrate success, but it is more important to heed the lessons of failure.", author: "Bill Gates" },
  { text: "It takes 20 years to build a reputation and five minutes to ruin it.", author: "Warren Buffett" },
  { text: "There are no secrets to success. It is the result of preparation, hard work, and learning from failure.", author: "Colin Powell" },
  { text: "Great things in business are never done by one person. They're done by a team of people.", author: "Steve Jobs" },
  { text: "A business has to be involving, it has to be fun, and it has to exercise your creative instincts.", author: "Richard Branson" },
  { text: "All our dreams can come true, if we have the courage to pursue them.", author: "Walt Disney" },
  { text: "The only way to do great work is to love what you do.", author: "Steve Jobs" },
  { text: "Innovation distinguishes between a leader and a follower.", author: "Steve Jobs" },
  { text: "Entrepreneurs must be willing to be misunderstood for long periods of time.", author: "Jeff Bezos" },
  { text: "Your brand is what other people say about you when you're not in the room.", author: "Jeff Bezos" },
  { text: "We see our customers as invited guests to a party, and we are the hosts.", author: "Jeff Bezos" },
  { text: "Success is liking yourself, liking what you do, and liking how you do it.", author: "Maya Angelou" },
  { text: "Nothing will work unless you do.", author: "Maya Angelou" },
  { text: "You don't build a business. You build people, and people build the business.", author: "Zig Ziglar" },
  { text: "Your attitude, not your aptitude, will determine your altitude.", author: "Zig Ziglar" },
  { text: "The complaining customer represents a huge opportunity for more business.", author: "Zig Ziglar" },
  { text: "If we don't understand people, we don't understand business.", author: "Simon Sinek" },
  { text: "Leadership is not about being in charge. It's about taking care of those in your charge.", author: "Simon Sinek" },
  { text: "All you have in business is your reputation, so it's very important that you keep your word.", author: "Richard Branson" },
  { text: "Success comes from listening to your customers.", author: "Richard Branson" },
  { text: "A big business starts small.", author: "Richard Branson" },
  { text: "Do not be embarrassed by your failures, learn from them and start again.", author: "Richard Branson" },
  { text: "Do what you can, with what you have, where you are.", author: "Theodore Roosevelt" },
  { text: "Whenever you see a successful business, someone once made a courageous decision.", author: "Peter Drucker" },
  { text: "The entrepreneur always searches for change, responds to it, and exploits it as an opportunity.", author: "Peter Drucker" },
  { text: "You never achieve real success unless you like what you are doing.", author: "Dale Carnegie" },
  { text: "Discouragement and failure are two of the surest stepping stones to success.", author: "Dale Carnegie" },
  { text: "Effort only fully releases its reward after a person refuses to quit.", author: "Napoleon Hill" },
  { text: "The way to get started is to quit talking and begin doing.", author: "Walt Disney" },
  { text: "I have not failed. I've just found 10,000 ways that won't work.", author: "Thomas Edison" },
  { text: "Price is what you pay. Value is what you get.", author: "Warren Buffett" },
  { text: "Risk comes from not knowing what you're doing.", author: "Warren Buffett" },
  { text: "If you can't feed a team with two pizzas, it's too large.", author: "Jeff Bezos" },
  { text: "Life is too short for long-term grudges.", author: "Elon Musk" },
  { text: "When something is important enough, you do it even if the odds are not in your favor.", author: "Elon Musk" },
  { text: "The biggest risk is not taking any risk.", author: "Mark Zuckerberg" },
  { text: "Ideas are easy. Implementation is hard.", author: "Guy Kawasaki" },
  { text: "High expectations are the key to everything.", author: "Sam Walton" },
  { text: "I didn't get there by wishing for it or hoping for it, but by working for it.", author: "Estée Lauder" },
  { text: "I have never worked a day in my life without selling.", author: "Estée Lauder" },
  { text: "Start where you are, use what you have, and believe in the possibilities.", author: "Sara Blakely" },
  { text: "The biggest adventure you can take is to live the life of your dreams.", author: "Oprah Winfrey" },
  { text: "You miss 100% of the shots you don't take.", author: "Wayne Gretzky" },
];

function getGreeting(date = new Date()) {
  const hour = date.getHours();
  if (hour < 12) return "Good Morning";
  if (hour < 18) return "Good Afternoon";
  return "Good Evening";
}

function getFirstName(profile) {
  const fullName = profile?.full_name?.trim();
  if (fullName) return fullName.split(/\s+/)[0];
  const email = profile?.email;
  if (email) return email.split("@")[0];
  return "there";
}

function pickRandomQuote() {
  return QUOTES[Math.floor(Math.random() * QUOTES.length)];
}

export default function DashboardGreeting({ profile }) {
  const greeting = getGreeting();
  const name = getFirstName(profile);
  // Lazy initializer — picked once when this component mounts (i.e. once per
  // Dashboard visit), not re-rolled on every re-render while it stays mounted.
  const [quote] = useState(pickRandomQuote);

  return (
    <div className="dashboard-greeting">
      <p className="dashboard-greeting__title">{greeting}, {name}</p>
      <p className="dashboard-greeting__quote">"{quote.text}" — {quote.author}</p>
    </div>
  );
}
