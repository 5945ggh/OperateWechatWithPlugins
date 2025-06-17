class PrintMsg(MsgResponser):
    """在控制台打印收到的消息"""
    async def execute(self, driver, listen_object, msg):
        print(f"<({listen_object.type}){listen_object.name} {msg.sender}>: {msg.content}")

class SaveMsg(MsgResponser):
    """
    将收到的消息保存到文件中
    """
    def __init__(self, description = None, save_path = "msg_history.txt"):
        super().__init__(description)
        self.save_path = save_path
    
    async def execute(self, driver, listen_object, msg):
        try:
            f = open(self.save_path, "a", encoding="utf-8")
        except FileNotFoundError:
            f = open(self.save_path, "w", encoding="utf-8")
        f.write(f"[{datetime.datetime.now()}]<({listen_object.type}){listen_object.name} {msg.sender}>: {msg.content}\n")
        f.close()

async def get_async_openai_response(
    client: AsyncOpenAI,
    model: str,
    sys_message: str,
    messages: List[Dict],
    temp: float = 1.0,
    max_tokens: int = 256
) -> str:
    """使用一个已初始化的异步OpenAI客户端，获取聊天回复。"""
    if not messages:
        return "" # 如果没有有效消息，直接返回
        
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": sys_message}] + messages,
        temperature=temp,
        max_tokens=max_tokens,
        stream=False
    )
    return response.choices[0].message.content


class ChatGPTResponser(MsgResponser):
    """一个使用 OpenAI API 进行智能回复的、经过优化的插件。"""
    
    def __init__(self, 
                 api_key: str, 
                 base_url: str, 
                 model: str,
                 trigger_words: List[str], 
                 sys_msg: str,
                 temp:float = 1.0,
                 random_reply_chance: float = 0.05):
        """
        初始化ChatGPT响应器。

        Args:
            api_key: OpenAI API密钥
            base_url: API的基地址
            model: 要使用的模型名称
            trigger_words: 触发AI回复的关键词列表
            sys_msg: 发送给AI的系统级指令 (System Prompt)
            random_reply_chance: 在群聊中随机回复的概率 (0到1之间)
        """
        super().__init__(description="连接到大语言模型进行智能回复")
        self.trigger_words = trigger_words
        self.sys_msg = sys_msg
        self.model = model
        self.temp = temp
        self.random_reply_chance = random_reply_chance

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        
    async def execute(self, driver: WxDriver, listen_object: ListenObject, msg: Message):

        if msg.type not in [MsgType.FRIEND]:
            return

        is_triggered = any(word in msg.content for word in self.trigger_words)
        is_random_chance = (listen_object.type == 'group' and random.random() < self.random_reply_chance)

        if is_triggered or is_random_chance:
            await self._generate_and_send_reply(driver, listen_object, msg, is_triggered)

    def _build_context(self, listen_object: ListenObject) -> List[Dict]:

        messages = []
        history = listen_object.get_messages() # 获取历史消息

        for m in history:
            role = None
            
            # 将自己的消息映射为 assistant
            if m.type == MsgType.SELF:
                role = "assistant"
            # 将好友/群友的消息映射为 user
            elif m.type == MsgType.FRIEND:
                role = "user"
               
            if role and m.content:
                if role == "assistant":
                    content = m.content
                else:
                    content = f"{m.sender}说: {m.content}"
                
                messages.append({"role": role, "content": content})
        
        return messages

    async def _generate_and_send_reply(self, driver: WxDriver, listen_object: ListenObject, msg: Message, is_triggered: bool):
  
        try:
            # 1. 构建上下文
            context_messages = self._build_context(listen_object)
            
            # 2. 调用API
            ai_response = await get_async_openai_response(
                client=self.client,
                model=self.model,
                sys_message=self.sys_msg,
                messages=context_messages,
                temp=self.temp
            )

            if not ai_response:
                return

            # 3. 发送回复
            # 如果是关键词触发的，直接at/回复；如果是随机触发的，用引用回复更礼貌
            if is_triggered:
                await driver.send_text(listen_object.name, f"{ai_response}")
            else:
                await driver.quote(msg, content=ai_response)

        except Exception as e:
            logging.error(f"调用OpenAI或发送消息时出错: {e}", exc_info=True)
            # 只在明确触发时才发送错误报告，避免随机回复失败时打扰用户
            if is_triggered:
                await driver.quote(msg, content="我要说啥来着")
