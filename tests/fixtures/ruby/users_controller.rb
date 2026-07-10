class UsersController < ApplicationController
  def show
    @user = User.find(params[:id])
    render json: @user
  end

  def create
    ActiveRecord::Base.connection.execute("INSERT INTO users (name) VALUES ('x')")
  end
end

get '/users/:id', to: 'users#show'
post '/users', to: 'users#create'

def helper_method(x)
  x.to_s
end
