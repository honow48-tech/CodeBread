package main

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

type User struct {
	ID   int
	Name string
}

func getUser(c *gin.Context) {
	id := c.Param("id")
	user := findUserByID(id)
	c.JSON(http.StatusOK, user)
}

func createUser(c *gin.Context) {
	sql := "INSERT INTO users (name) VALUES ($1)"
	db.Exec(sql, c.PostForm("name"))
	c.Status(http.StatusCreated)
}

func main() {
	r := gin.Default()
	r.GET("/users/:id", getUser)
	r.POST("/users", createUser)
	r.Run()
}
