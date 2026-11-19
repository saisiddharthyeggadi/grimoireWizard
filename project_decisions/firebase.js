// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyBXnABlmhF2Rx3QoL5RmonbDYVPYednu8A",
  authDomain: "grimoirewizard-b8dea.firebaseapp.com",
  projectId: "grimoirewizard-b8dea",
  storageBucket: "grimoirewizard-b8dea.firebasestorage.app",
  messagingSenderId: "322231922314",
  appId: "1:322231922314:web:9986f0efe6f72dc55c8773",
  measurementId: "G-GCXEKPLZYH"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);

// npm install firebase
// npm install -g firebase-tools
// firebase login
// firebase init

// "site": "grimoirewizard-b8dea-e0494",

// firebase deploy --only hosting:grimoirewizard-b8dea-e0494