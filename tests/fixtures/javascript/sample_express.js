// Sample Express app used as a parser test fixture.
const express = require("express");
const mongoose = require("mongoose");

const app = express();

const userSchema = new mongoose.Schema({
  name: String,
  email: String,
});
const User = mongoose.model("User", userSchema);

class UserService {
  async getById(id) {
    return User.findById(id);
  }
}

async function fetchExternalProfile(userId) {
  const res = await fetch(`https://api.example.com/profiles/${userId}`);
  return res.json();
}

async function getUser(req, res) {
  const user = await User.findById(req.params.id);
  res.json(user);
}

async function createUser(req, res) {
  await db.query("INSERT INTO users (name) VALUES (?)", [req.body.name]);
  res.status(201).send();
}

app.get("/users/:id", getUser);
app.post("/users", createUser);
